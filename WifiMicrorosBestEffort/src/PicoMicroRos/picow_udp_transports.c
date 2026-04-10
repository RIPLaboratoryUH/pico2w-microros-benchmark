#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/cyw43_arch.h"
#include "lwip/pbuf.h"
#include "lwip/udp.h"

#include <uxr/client/profile/transport/custom/custom_transport.h>
#include <picow_udp_transports.h>

// ─── POSIX shims required by micro-ROS on bare-metal ──────────────────────────
void usleep(uint64_t us)
{
    sleep_us(us);
}

int clock_gettime(clockid_t unused, struct timespec *tp)
{
    uint64_t m = time_us_64();
    tp->tv_sec = m / 1000000;
    tp->tv_nsec = (m % 1000000) * 1000;
    return 0;
}

// ─── RX ring buffer ───────────────────────────────────────────────────────────
// In threadsafe_background mode, callback_recv runs from the CYW43 IRQ /
// lwIP context, while picow_udp_transport_read runs from the main thread.
// The ring buffer decouples the two. On RP2040, uint8_t index writes are
// atomic, so head/tail don't need explicit locks — but we still wrap buffer
// access with cyw43_arch_lwip_begin/end on the reader side to serialise
// against the lwIP stack cleanly.

#define TRANS_RECV_RING_SIZE 32
#define TRANS_RECV_MAX_LEN   512

static uint8_t  trans_recv_ring[TRANS_RECV_RING_SIZE][TRANS_RECV_MAX_LEN];
static uint16_t trans_recv_len_ring[TRANS_RECV_RING_SIZE];
static volatile uint8_t trans_recv_head = 0;  // written by callback, read by reader
static volatile uint8_t trans_recv_tail = 0;  // written by reader, read by callback

static void callback_recv(void *arg, struct udp_pcb *pcb, struct pbuf *p,
                          const ip_addr_t *addr, u16_t port)
{
    ST_PICOW_TRANSPORT_PARAMS* params = (ST_PICOW_TRANSPORT_PARAMS*) arg;

    // NOTE: this callback is invoked from the lwIP context with the lwIP lock
    // already held, so we must NOT call cyw43_arch_lwip_begin/end here.
    if (params && ip_addr_cmp(addr, &params->ipaddr)) {
        uint8_t next_head = (trans_recv_head + 1) % TRANS_RECV_RING_SIZE;

        uint16_t len = pbuf_copy_partial(p, trans_recv_ring[trans_recv_head],
                                         TRANS_RECV_MAX_LEN, 0);
        trans_recv_len_ring[trans_recv_head] = len;
        trans_recv_head = next_head;

        // Overflow: drop oldest by advancing tail
        if (trans_recv_head == trans_recv_tail) {
            trans_recv_tail = (trans_recv_tail + 1) % TRANS_RECV_RING_SIZE;
        }
    }
    pbuf_free(p);
}

// ─── Transport open / close ───────────────────────────────────────────────────
bool picow_udp_transport_open(struct uxrCustomTransport * transport)
{
    ST_PICOW_TRANSPORT_PARAMS* params = (ST_PICOW_TRANSPORT_PARAMS*) transport->args;

    if (params) {
        cyw43_arch_lwip_begin();
        params->pcb = udp_new();
        ipaddr_aton(ROS_AGENT_IP_ADDR, &(params->ipaddr));
        params->port = ROS_AGENT_UDP_PORT;

        udp_recv(params->pcb, callback_recv, params);
        cyw43_arch_lwip_end();

        return true;
    }
    return false;
}

bool picow_udp_transport_close(struct uxrCustomTransport * transport)
{
    ST_PICOW_TRANSPORT_PARAMS* params = (ST_PICOW_TRANSPORT_PARAMS*) transport->args;

    if (params) {
        cyw43_arch_lwip_begin();
        udp_remove(params->pcb);
        cyw43_arch_lwip_end();
    }
    return true;
}

// ─── Transport write ──────────────────────────────────────────────────────────
size_t picow_udp_transport_write(struct uxrCustomTransport* transport,
                                 const uint8_t* buf,
                                 size_t len,
                                 uint8_t* err)
{
    ST_PICOW_TRANSPORT_PARAMS* params = (ST_PICOW_TRANSPORT_PARAMS*) transport->args;

    cyw43_arch_lwip_begin();

    struct pbuf* p = pbuf_alloc(PBUF_TRANSPORT, len, PBUF_RAM);
    if (p == NULL) {
        cyw43_arch_lwip_end();
        *err = 1;
        return 0;
    }

    memcpy(p->payload, buf, len);
    err_t lwip_err = udp_sendto(params->pcb, p, &params->ipaddr, params->port);
    pbuf_free(p);

    cyw43_arch_lwip_end();

    if (lwip_err != ERR_OK) {
        *err = 1;
        return 0;
    }
    return len;
}

// ─── Transport read ───────────────────────────────────────────────────────────
size_t picow_udp_transport_read(struct uxrCustomTransport * transport,
                                uint8_t *buf, size_t len, int timeout,
                                uint8_t *errcode)
{
    size_t recv_len = 0;
    *errcode = 1;

    // In threadsafe_background mode, packets are delivered automatically by
    // the lwIP/CYW43 IRQ context — no manual poll required. We just check
    // the ring buffer and return what's available (non-blocking).
    //
    // If timeout > 0 and no data is available, briefly wait so the executor
    // can yield useful CPU back to the system rather than hot-spinning.

    absolute_time_t deadline = make_timeout_time_ms(timeout > 0 ? timeout : 0);

    do {
        if (trans_recv_tail != trans_recv_head) {
            cyw43_arch_lwip_begin();

            uint16_t avail_len = trans_recv_len_ring[trans_recv_tail];
            recv_len = (avail_len >= len) ? len : avail_len;
            memcpy(buf, trans_recv_ring[trans_recv_tail], recv_len);
            trans_recv_tail = (trans_recv_tail + 1) % TRANS_RECV_RING_SIZE;

            cyw43_arch_lwip_end();

            *errcode = 0;
            return recv_len;
        }

        if (timeout <= 0) break;
        sleep_us(100);
    } while (!time_reached(deadline));

    return recv_len;
}

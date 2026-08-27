/* CHIPFORGE native PipeWire PCM sink. Reads signed S16LE stereo from stdin. */
#include <pipewire/pipewire.h>
#include <spa/param/audio/format-utils.h>
#include <spa/param/audio/raw.h>
#include <spa/utils/result.h>
#include <errno.h>
#include <signal.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define RING_BYTES (1u << 16)
static uint8_t ringbuf[RING_BYTES];
static _Atomic uint64_t write_pos = 0, read_pos = 0;
static struct pw_main_loop *main_loop;

static void on_signal(int sig) { (void)sig; if (main_loop) pw_main_loop_quit(main_loop); }

static void on_process(void *userdata) {
    struct pw_stream *stream = userdata;
    struct pw_buffer *pb = pw_stream_dequeue_buffer(stream);
    if (!pb) return;
    struct spa_buffer *b = pb->buffer;
    if (!b->datas[0].data) { pw_stream_queue_buffer(stream, pb); return; }
    uint32_t capacity = b->datas[0].maxsize;
    uint64_t r = __atomic_load_n(&read_pos, __ATOMIC_ACQUIRE);
    uint64_t w = __atomic_load_n(&write_pos, __ATOMIC_ACQUIRE);
    uint32_t available = (uint32_t)((w - r) > capacity ? capacity : (w - r));
    uint8_t *dst = b->datas[0].data;
    uint32_t first = available;
    if ((r % RING_BYTES) + first > RING_BYTES) first = RING_BYTES - (uint32_t)(r % RING_BYTES);
    memcpy(dst, ringbuf + (r % RING_BYTES), first);
    memcpy(dst + first, ringbuf, available - first);
    if (available < capacity) memset(dst + available, 0, capacity - available);
    __atomic_store_n(&read_pos, r + available, __ATOMIC_RELEASE);
    b->datas[0].chunk->offset = 0;
    b->datas[0].chunk->stride = 4;
    b->datas[0].chunk->size = capacity;
    pw_stream_queue_buffer(stream, pb);
}

static const struct pw_stream_events stream_events = {
    PW_VERSION_STREAM_EVENTS,
    .process = on_process,
};

static void *reader_thread(void *unused) {
    (void)unused;
    uint8_t input[16384];
    for (;;) {
        uint64_t w = __atomic_load_n(&write_pos, __ATOMIC_RELAXED);
        uint64_t r = __atomic_load_n(&read_pos, __ATOMIC_ACQUIRE);
        uint64_t free_bytes = RING_BYTES - (w - r);
        if (free_bytes < 4096) {
            const struct timespec pause = { .tv_sec = 0, .tv_nsec = 1000000 };
            nanosleep(&pause, NULL);
            continue;
        }
        size_t request = sizeof input;
        if (request > free_bytes) request = (size_t)free_bytes;
        request -= request % 4;
        ssize_t got = read(STDIN_FILENO, input, request);
        if (got == 0) { pw_main_loop_quit(main_loop); return NULL; }
        if (got < 0) { if (errno == EINTR) continue; pw_main_loop_quit(main_loop); return NULL; }
        size_t first = (size_t)got;
        if ((w % RING_BYTES) + first > RING_BYTES) first = RING_BYTES - (size_t)(w % RING_BYTES);
        memcpy(ringbuf + (w % RING_BYTES), input, first);
        memcpy(ringbuf, input + first, (size_t)got - first);
        __atomic_store_n(&write_pos, w + (uint64_t)got, __ATOMIC_RELEASE);
    }
}

int main(int argc, char **argv) {
    uint32_t rate = argc > 1 ? (uint32_t)strtoul(argv[1], NULL, 10) : 44100;
    uint32_t channels = argc > 2 ? (uint32_t)strtoul(argv[2], NULL, 10) : 2;
    pw_init(&argc, &argv);
    main_loop = pw_main_loop_new(NULL);
    if (!main_loop) return 2;
    struct pw_context *context = pw_context_new(pw_main_loop_get_loop(main_loop), NULL, 0);
    struct pw_core *core = pw_context_connect(context, NULL, 0);
    if (!core) { fprintf(stderr, "CHIPFORGE: cannot connect to PipeWire\n"); return 3; }
    struct pw_stream *stream = pw_stream_new(core, "CHIPFORGE WORKSTATION", pw_properties_new(
        PW_KEY_MEDIA_TYPE, "Audio", PW_KEY_MEDIA_CATEGORY, "Playback",
        PW_KEY_MEDIA_ROLE, "Music", PW_KEY_NODE_NAME, "chipforge", NULL));
    struct spa_hook listener;
    pw_stream_add_listener(stream, &listener, &stream_events, stream);
    uint8_t buffer[1024]; struct spa_pod_builder builder = SPA_POD_BUILDER_INIT(buffer, sizeof buffer);
    struct spa_audio_info_raw info = {0};
    info.format = SPA_AUDIO_FORMAT_S16_LE;
    info.rate = rate;
    info.channels = channels;
    const struct spa_pod *params[1];
    params[0] = spa_format_audio_raw_build(&builder, SPA_PARAM_EnumFormat, &info);
    int result = pw_stream_connect(stream, PW_DIRECTION_OUTPUT, PW_ID_ANY,
        PW_STREAM_FLAG_AUTOCONNECT | PW_STREAM_FLAG_MAP_BUFFERS | PW_STREAM_FLAG_RT_PROCESS,
        params, 1);
    if (result < 0) { fprintf(stderr, "CHIPFORGE: PipeWire stream failed: %s\n", spa_strerror(result)); return 4; }
    signal(SIGINT, on_signal); signal(SIGTERM, on_signal);
    pthread_t reader; pthread_create(&reader, NULL, reader_thread, NULL);
    pw_main_loop_run(main_loop);
    pthread_cancel(reader); pthread_join(reader, NULL);
    pw_stream_destroy(stream); pw_core_disconnect(core); pw_context_destroy(context); pw_main_loop_destroy(main_loop); pw_deinit();
    return 0;
}

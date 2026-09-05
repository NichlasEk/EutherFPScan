/* Synthetic ABI fixture: never communicates with hardware. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/wait.h>
#include <time.h>
struct pipe_handle { unsigned int mode; char *path; int fd; };
/* Reproduce the vendor's single-read bug. The executable must interpose it. */
int palPipeRead(struct pipe_handle *p, void *data, unsigned int count) {
    return read(p->fd, data, count) == (ssize_t)count ? 0 : 40;
}
static void noop(int sig) { (void)sig; }
static int pipe_fixture(void) {
    const char *mode = getenv("MOCK_PIPE");
    if (!mode) return 1;
    unsigned char buffer[70759], payload[70759];
    memset(payload, 0x5a, sizeof(payload));
    int fds[2];
    if (pipe(fds) || fcntl(fds[0], F_SETPIPE_SZ, 4096) < 0) return 0;
    struct sigaction action = {0};
    action.sa_handler = noop;
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGUSR1, &action, NULL)) return 0;
    pid_t child = fork();
    if (child < 0) return 0;
    if (!child) {
        close(fds[0]);
        struct timespec delay = {.tv_nsec = 20000000};
        nanosleep(&delay, NULL);
        if (!strcmp(mode, "interrupt"))
            kill(getppid(), SIGUSR1); /* EINTR before data, without SA_RESTART. */
        nanosleep(&delay, NULL);
        if (write(fds[1], payload, 123) != 123) _exit(2);
        nanosleep(&delay, NULL);
        if (!strcmp(mode, "eof")) { close(fds[1]); _exit(0); }
        size_t sent = 123;
        while (sent < sizeof(payload)) {
            ssize_t n = write(fds[1], payload + sent, sizeof(payload) - sent);
            if (n < 0 && errno == EINTR) continue;
            if (n <= 0) _exit(2);
            sent += (size_t)n;
        }
        close(fds[1]);
        _exit(0);
    }
    close(fds[1]);
    struct pipe_handle handle = {0, "/unused", fds[0]};
    int result = palPipeRead(&handle, buffer, sizeof(buffer));
    close(fds[0]);
    int status;
    while (waitpid(child, &status, 0) < 0 && errno == EINTR) {}
    return result == 0 && !memcmp(buffer, payload, sizeof(buffer)) ? 1 : 0;
}
static void hang_at(const char *stage) {
    const char *requested = getenv("MOCK_HANG");
    if (requested && !strcmp(requested, stage)) sleep(5);
}
struct vfs_data { void *ctx, *image, *enroll; };
int vfs_wait_for_service(void) { return 0; }
int vfs_set_matcher_type(int type) { return type == 3 ? 0 : -1; }
int vfs_dev_init(struct vfs_data *d) { (void)d; hang_at("device_init"); puts("vendor stdout noise"); return 0; }
int vfs_capture(struct vfs_data *d, int mode) { (void)d; (void)mode; hang_at("capture_wait_for_swipe"); return pipe_fixture(); }
int vfs_get_img_width(struct vfs_data *d) { (void)d; return 2; }
int vfs_get_img_height(struct vfs_data *d) { (void)d; return 2; }
int vfs_get_img_datasize(struct vfs_data *d) { (void)d; return getenv("MOCK_BAD") ? 3 : 4; }
unsigned char *vfs_get_img_data(struct vfs_data *d) { (void)d; return (unsigned char *)"abcd"; }
void vfs_free_img_data(unsigned char *p) { (void)p; }
void vfs_clean_handles(struct vfs_data *d) { (void)d; hang_at("clean_handles"); }
void vfs_dev_exit(struct vfs_data *d) { (void)d; }

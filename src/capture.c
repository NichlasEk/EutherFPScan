/* VFS wrapper ABI reference: docs/driver-review.md.
 * Run under a supervisor: vendor calls may block indefinitely.
 * stdout protocol: EFP1, big-endian uint32 width and height, grayscale bytes.
 */
#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

struct vfs_data { void *ctx, *image, *enroll; };
static int output_fd;

static void *symbol(void *lib, const char *name)
{
    void *p = dlsym(lib, name);
    if (!p) { fprintf(stderr, "Missing symbol: %s\n", name); exit(2); }
    return p;
}

static int send_all(const void *data, size_t size)
{
    const unsigned char *p = data;
    while (size) {
        ssize_t n = write(output_fd, p, size);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        p += n;
        size -= (size_t)n;
    }
    return 0;
}

int main(int argc, char **argv)
{
    if (argc != 3 || (strcmp(argv[1], "--probe") && strcmp(argv[1], "--probe-lazy") && strcmp(argv[1], "--capture"))) {
        fprintf(stderr, "Usage: %s --probe|--probe-lazy|--capture /absolute/wrapper.so\n", argv[0]);
        return 2;
    }
    /* Vendor diagnostics must never enter the binary image stream. */
    output_fd = dup(STDOUT_FILENO);
    if (output_fd < 0 || dup2(STDERR_FILENO, STDOUT_FILENO) < 0) return 2;
    /* Vendor library has unresolved optional matcher symbols. Strict probe
     * exposes these; lazy mode matches the legacy helper's binding behavior. */
    int binding = !strcmp(argv[1], "--probe") ? RTLD_NOW : RTLD_LAZY;
    void *lib = dlopen(argv[2], binding | RTLD_LOCAL);
    if (!lib) { fprintf(stderr, "%s\n", dlerror()); return 2; }
    int (*wait_service)(void) = symbol(lib, "vfs_wait_for_service");
    int (*matcher)(int) = symbol(lib, "vfs_set_matcher_type");
    int (*init)(struct vfs_data *) = symbol(lib, "vfs_dev_init");
    int (*capture)(struct vfs_data *, int) = symbol(lib, "vfs_capture");
    int (*width)(struct vfs_data *) = symbol(lib, "vfs_get_img_width");
    int (*height)(struct vfs_data *) = symbol(lib, "vfs_get_img_height");
    int (*length)(struct vfs_data *) = symbol(lib, "vfs_get_img_datasize");
    unsigned char *(*data)(struct vfs_data *) = symbol(lib, "vfs_get_img_data");
    void (*free_data)(unsigned char *) = symbol(lib, "vfs_free_img_data");
    void (*clean)(struct vfs_data *) = symbol(lib, "vfs_clean_handles");
    void (*dev_exit)(struct vfs_data *) = symbol(lib, "vfs_dev_exit");
    if (strcmp(argv[1], "--capture")) {
        fprintf(stderr, "Wrapper loaded (%s); 11 API symbols found. No API calls made.\n",
                binding == RTLD_NOW ? "strict" : "lazy: other symbols remain unchecked");
        dlclose(lib);
        return 0;
    }
    struct vfs_data dev = {0};
    if (wait_service() != 0 || matcher(3) != 0 || init(&dev) != 0) {
        fprintf(stderr, "VFS initialization failed\n");
        return 3;
    }
    int result = 3;
    unsigned char *pixels = NULL;
    if (capture(&dev, 1) != 1) goto cleanup;
    int w = width(&dev), h = height(&dev), n = length(&dev);
    pixels = data(&dev);
    if (!pixels || w <= 0 || h <= 0 || w > 2048 || h > 2048 ||
        n != w * h) {
        fprintf(stderr, "Invalid image metadata: %d x %d, %d bytes\n", w, h, n);
        goto cleanup;
    }
    uint32_t dims[] = {htonl((uint32_t)w), htonl((uint32_t)h)};
    if (!send_all("EFP1", 4) && !send_all(dims, sizeof(dims)) &&
        !send_all(pixels, (size_t)n)) result = 0;
cleanup:
    if (pixels) free_data(pixels);
    clean(&dev);
    dev_exit(&dev);
    dlclose(lib);
    close(output_fd);
    return result;
}

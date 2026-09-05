/* Exact-read compatibility shim for HP's x86-64 libvfsFprintWrapper.
 * ABI verified against palPipeRead/palPipeOpen in the pinned HP binary.
 * Exported only by euther-capture; does not replace libc read or USB I/O.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <stddef.h>
#include <stdint.h>
#include <unistd.h>

struct vfs_pipe {
    uint32_t mode;
    char *path;
    int fd;
};
_Static_assert(offsetof(struct vfs_pipe, path) == 8, "VFS x86-64 pipe ABI");
_Static_assert(offsetof(struct vfs_pipe, fd) == 16, "VFS x86-64 pipe ABI");

int palPipeRead(struct vfs_pipe *pipe, void *buffer, unsigned int count)
{
    /* Preserve vendor failure codes: 40 for read failure, 207 for open. */
    if (!pipe || !buffer || !pipe->path || !count || count > 8U * 1024U * 1024U)
        return 40;
    if (pipe->fd == -1) {
        do {
            pipe->fd = open(pipe->path, O_RDONLY);
        } while (pipe->fd < 0 && errno == EINTR);
        if (pipe->fd < 0) return 207;
    }
    unsigned char *output = buffer;
    size_t received = 0;
    while (received < count) {
        ssize_t n = read(pipe->fd, output + received, count - received);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return 40; /* EOF/error is not a complete message. */
        received += (size_t)n;
    }
    return 0;
}

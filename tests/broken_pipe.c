/* Native fixture: Python itself ignores SIGPIPE, so a Python child cannot
 * detect an exec-time signal-disposition regression. No device access. */
#include <errno.h>
#include <stdio.h>
#include <unistd.h>

int main(void)
{
    int fds[2];
    if (pipe(fds) != 0) return 2;
    close(fds[0]);
    ssize_t result = write(fds[1], "x", 1);
    int error = errno;
    close(fds[1]);
    if (result == -1 && error == EPIPE) {
        puts("EPIPE reported; process survived");
        return 0;
    }
    return 3;
}

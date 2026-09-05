/* Synthetic ABI fixture: never communicates with hardware. */
#include <stdio.h>
#include <stdlib.h>
struct vfs_data { void *ctx, *image, *enroll; };
int vfs_wait_for_service(void) { return 0; }
int vfs_set_matcher_type(int type) { return type == 3 ? 0 : -1; }
int vfs_dev_init(struct vfs_data *d) { (void)d; puts("vendor stdout noise"); return 0; }
int vfs_capture(struct vfs_data *d, int mode) { (void)d; (void)mode; return 1; }
int vfs_get_img_width(struct vfs_data *d) { (void)d; return 2; }
int vfs_get_img_height(struct vfs_data *d) { (void)d; return 2; }
int vfs_get_img_datasize(struct vfs_data *d) { (void)d; return getenv("MOCK_BAD") ? 3 : 4; }
unsigned char *vfs_get_img_data(struct vfs_data *d) { (void)d; return (unsigned char *)"abcd"; }
void vfs_free_img_data(unsigned char *p) { (void)p; }
void vfs_clean_handles(struct vfs_data *d) { (void)d; }
void vfs_dev_exit(struct vfs_data *d) { (void)d; }

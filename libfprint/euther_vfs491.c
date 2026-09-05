/* SPDX-License-Identifier: LGPL-2.1-or-later
 * EutherFPScan image transport for libfprint 1.94.9.
 * Only a live, same-uid Unix peer may supply a capture. fprintd runs as root.
 */
#define FP_COMPONENT "euther_vfs491"
#include "drivers_api.h"
#include <gio/gunixsocketaddress.h>
#include <string.h>
#include <unistd.h>

struct _FpiDeviceEutherVfs491
{
  FpImageDevice parent;
  GCancellable *io_cancel;
  gboolean pending;
  gboolean deactivating;
};
G_DECLARE_FINAL_TYPE (FpiDeviceEutherVfs491, fpi_device_euther_vfs491, FPI, DEVICE_EUTHER_VFS491, FpImageDevice)
G_DEFINE_TYPE (FpiDeviceEutherVfs491, fpi_device_euther_vfs491, FP_TYPE_IMAGE_DEVICE)

static gboolean
read_exact (GInputStream *input, void *data, gsize length,
            GCancellable *cancel, GError **error)
{
  gsize got = 0;
  if (!g_input_stream_read_all (input, data, length, &got, cancel, error))
    return FALSE;
  if (got != length)
    {
      g_set_error_literal (error, G_IO_ERROR, G_IO_ERROR_PARTIAL_INPUT,
                           "Euther capture response was truncated");
      return FALSE;
    }
  return TRUE;
}

static void
capture_thread (GTask *task, gpointer source, gpointer path, GCancellable *cancel)
{
  g_autoptr(GError) error = NULL;
  g_autoptr(GSocketClient) client = g_socket_client_new ();
  g_autoptr(GSocketAddress) address = g_unix_socket_address_new (path);
  g_autoptr(GSocketConnection) connection = NULL;
  g_autoptr(GCredentials) credentials = NULL;
  g_autoptr(FpImage) image = NULL;
  GInputStream *input;
  guint8 header[12], extra;
  guint32 width, height;
  gsize sent;
  (void) source;

  g_socket_client_set_timeout (client, 40);
  connection = g_socket_client_connect (client, G_SOCKET_CONNECTABLE (address), cancel, &error);
  if (!connection)
    goto fail;
  credentials = g_socket_get_credentials (g_socket_connection_get_socket (connection), &error);
  if (!credentials)
    goto fail;
  if (g_credentials_get_unix_user (credentials, &error) != geteuid ())
    {
      if (!error)
        error = g_error_new_literal (G_IO_ERROR, G_IO_ERROR_PERMISSION_DENIED,
                                     "Euther capture peer has an unexpected uid");
      goto fail;
    }
  if (error)
    goto fail;
  if (!g_output_stream_write_all (g_io_stream_get_output_stream (G_IO_STREAM (connection)),
                                  "C", 1, &sent, cancel, &error))
    goto fail;
  input = g_io_stream_get_input_stream (G_IO_STREAM (connection));
  if (!read_exact (input, header, sizeof header, cancel, &error))
    goto fail;
  memcpy (&width, header + 4, 4);
  memcpy (&height, header + 8, 4);
  width = GUINT32_FROM_BE (width);
  height = GUINT32_FROM_BE (height);
  if (memcmp (header, "EFP1", 4) || width == 0 || height == 0 ||
      width > 2048 || height > 2048)
    {
      error = g_error_new_literal (G_IO_ERROR, G_IO_ERROR_INVALID_DATA,
                                   "Euther service returned an error or invalid image header");
      goto fail;
    }
  image = fp_image_new (width, height);
  /* Normalization used by the original VFS image driver. */
  image->flags = FPI_IMAGE_COLORS_INVERTED | FPI_IMAGE_V_FLIPPED;
  if (!read_exact (input, image->data, width * height, cancel, &error))
    goto fail;
  if (g_input_stream_read (input, &extra, 1, cancel, &error) != 0)
    {
      if (!error)
        error = g_error_new_literal (G_IO_ERROR, G_IO_ERROR_INVALID_DATA,
                                     "Trailing bytes in Euther capture response");
      goto fail;
    }
  g_task_return_pointer (task, g_steal_pointer (&image), g_object_unref);
  return;
fail:
  g_task_return_error (task, g_steal_pointer (&error));
}

static void
capture_done (GObject *object, GAsyncResult *result, gpointer unused)
{
  FpiDeviceEutherVfs491 *self = FPI_DEVICE_EUTHER_VFS491 (object);
  FpImageDevice *device = FP_IMAGE_DEVICE (self);
  g_autoptr(GError) error = NULL;
  g_autoptr(FpImage) image = g_task_propagate_pointer (G_TASK (result), &error);
  (void) unused;
  self->pending = FALSE;
  g_clear_object (&self->io_cancel);
  if (self->deactivating)
    {
      self->deactivating = FALSE;
      fpi_image_device_deactivate_complete (device, NULL);
      return;
    }
  if (error)
    {
      fpi_image_device_session_error (device, g_steal_pointer (&error));
      return;
    }
  fpi_image_device_report_finger_status (device, TRUE);
  fpi_image_device_image_captured (device, g_steal_pointer (&image));
  fpi_image_device_report_finger_status (device, FALSE);
}

static void
state_changed (FpImageDevice *device, FpiImageDeviceState state)
{
  FpiDeviceEutherVfs491 *self = FPI_DEVICE_EUTHER_VFS491 (device);
  g_autoptr(GTask) task = NULL;
  if (state != FPI_IMAGE_DEVICE_STATE_AWAIT_FINGER_ON || self->pending)
    return;
  self->io_cancel = g_cancellable_new ();
  self->pending = TRUE;
  task = g_task_new (self, self->io_cancel, capture_done, NULL);
  g_task_set_task_data (task, g_strdup (fpi_device_get_virtual_env (FP_DEVICE (device))), g_free);
  g_task_run_in_thread (task, capture_thread);
}

static void
device_open (FpImageDevice *device)
{
  const char *path = fpi_device_get_virtual_env (FP_DEVICE (device));
  if (!path || !g_path_is_absolute (path))
    {
      fpi_image_device_open_complete (device,
                                      fpi_device_error_new (FP_DEVICE_ERROR_DATA_INVALID));
      return;
    }
  fpi_image_device_open_complete (device, NULL);
}

static void
device_close (FpImageDevice *device)
{
  fpi_image_device_close_complete (device, NULL);
}

static void
activate (FpImageDevice *device)
{
  fpi_image_device_activate_complete (device, NULL);
}

static void
deactivate (FpImageDevice *device)
{
  FpiDeviceEutherVfs491 *self = FPI_DEVICE_EUTHER_VFS491 (device);
  if (self->pending)
    {
      self->deactivating = TRUE;
      g_cancellable_cancel (self->io_cancel);
    }
  else
    fpi_image_device_deactivate_complete (device, NULL);
}

static void
fpi_device_euther_vfs491_init (FpiDeviceEutherVfs491 *self)
{
  (void) self;
}

static const FpIdEntry ids[] = {
  { .virtual_envvar = "FP_EUTHER_VFS491" },
  { .virtual_envvar = NULL }
};

static void
fpi_device_euther_vfs491_class_init (FpiDeviceEutherVfs491Class *klass)
{
  FpDeviceClass *device = FP_DEVICE_CLASS (klass);
  FpImageDeviceClass *image = FP_IMAGE_DEVICE_CLASS (klass);
  device->id = FP_COMPONENT;
  device->full_name = "EutherFPScan Validity VFS491";
  device->type = FP_DEVICE_TYPE_VIRTUAL;
  device->id_table = ids;
  device->nr_enroll_stages = 5;
  device->scan_type = FP_SCAN_TYPE_SWIPE;
  image->img_open = device_open;
  image->img_close = device_close;
  image->activate = activate;
  image->deactivate = deactivate;
  image->change_state = state_changed;
}

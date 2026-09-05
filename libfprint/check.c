/* SPDX-License-Identifier: LGPL-2.1-or-later
 * Integration harness: keeps templates only in memory; never changes PAM.
 */
#include <libfprint/fprint.h>
#include <stdio.h>
#include <string.h>

static gboolean cancel_capture (gpointer data)
{
  g_cancellable_cancel (data);
  return G_SOURCE_REMOVE;
}

static void progress (FpDevice *device, gint stage, FpPrint *print, gpointer data, GError *error)
{
  (void) device; (void) print; (void) data;
  printf ("ENROLL_STAGE %d %s\n", stage, error ? error->message : "ok");
  fflush (stdout);
}

int main (int argc, char **argv)
{
  g_autoptr(FpContext) context = fp_context_new ();
  g_autoptr(GError) error = NULL;
  GPtrArray *devices = fp_context_get_devices (context);
  FpDevice *device = NULL;
  if (argc != 2) return 2;
  for (guint i = 0; i < devices->len; i++)
    if (!strcmp (fp_device_get_driver (devices->pdata[i]), "euther_vfs491"))
      device = devices->pdata[i];
  if (!device) { fprintf (stderr, "No Euther device\n"); return 2; }
  if (!fp_device_open_sync (device, NULL, &error)) goto fail;
  printf ("DEVICE %s; enroll stages %d\n", fp_device_get_name (device),
          fp_device_get_nr_enroll_stages (device));
  if (!strcmp (argv[1], "capture") || !strcmp (argv[1], "cancel") || !strcmp (argv[1], "cancel-retry"))
    {
      g_autoptr(GCancellable) cancel = g_cancellable_new ();
      gboolean cancelling = g_str_has_prefix (argv[1], "cancel");
      guint timer = cancelling ? g_timeout_add (150, cancel_capture, cancel) : 0;
      g_autoptr(FpImage) image = fp_device_capture_sync (device, TRUE, cancel, &error);
      if (timer && !g_cancellable_is_cancelled (cancel)) g_source_remove (timer);
      if (cancelling)
        {
          if (!g_error_matches (error, G_IO_ERROR, G_IO_ERROR_CANCELLED)) goto fail;
          g_clear_error (&error);
          puts ("CANCELLED");
          if (!strcmp (argv[1], "cancel-retry"))
            {
              image = fp_device_capture_sync (device, TRUE, NULL, &error);
              if (!image) goto fail;
              puts ("CAPTURE_AFTER_CANCEL_OK");
            }
        }
      else
        {
          if (!image) goto fail;
          printf ("IMAGE %u %u\n", fp_image_get_width (image), fp_image_get_height (image));
        }
    }
  else if (!strcmp (argv[1], "roundtrip"))
    {
      g_autoptr(FpPrint) template = g_object_ref_sink (fp_print_new (device));
      g_autoptr(FpPrint) enrolled = fp_device_enroll_sync (device, template, NULL, progress, NULL, &error);
      g_autoptr(FpPrint) restored = NULL;
      g_autofree guchar *bytes = NULL;
      gsize length = 0;
      gboolean match = FALSE;
      if (!enrolled || !fp_print_serialize (enrolled, &bytes, &length, &error)) goto fail;
      restored = fp_print_deserialize (bytes, length, &error);
      if (!restored) goto fail;
      puts ("ENROLLED_AND_RESTORED");
      if (!fp_device_verify_sync (device, restored, NULL, NULL, NULL, &match, NULL, &error)) goto fail;
      printf ("SAME_IMAGE_MATCH %d\n", match);
      if (!match)
        {
          g_set_error_literal (&error, G_IO_ERROR, G_IO_ERROR_FAILED, "Same image did not match");
          goto fail;
        }
      if (!fp_device_verify_sync (device, restored, NULL, NULL, NULL, &match, NULL, &error)) goto fail;
      printf ("OTHER_IMAGE_MATCH %d\n", match);
      if (match)
        {
          g_set_error_literal (&error, G_IO_ERROR, G_IO_ERROR_FAILED, "Different image unexpectedly matched");
          goto fail;
        }
    }
  else return 2;
  if (!fp_device_close_sync (device, NULL, &error)) goto fail;
  puts ("CLOSED");
  return 0;
fail:
  fprintf (stderr, "FAILED: %s\n", error ? error->message : "unexpected result");
  if (fp_device_is_open (device)) fp_device_close_sync (device, NULL, NULL);
  return 1;
}

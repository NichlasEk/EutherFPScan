"""GTK desktop interface. Polkit handles authentication; the GUI stays unprivileged."""
from pathlib import Path
import sys
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, Gio, GLib
from .backend import Registry, FINGERS, FINGER_NAMES

BASE = Path(__file__).resolve().parent


def label(text, css=None, wrap=False):
    widget = Gtk.Label(label=text, xalign=0)
    if css:
        widget.get_style_context().add_class(css)
    widget.set_line_wrap(wrap)
    return widget


def box(vertical=True, spacing=0, css=None):
    widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing)
    if css:
        widget.get_style_context().add_class(css)
    return widget


def button(text, callback, css=None):
    widget = Gtk.Button(label=text)
    if css:
        widget.get_style_context().add_class(css)
    widget.connect('clicked', callback)
    return widget


class RegisWindow(Gtk.ApplicationWindow):
    def __init__(self, app, registry, preview=False):
        super().__init__(application=app, title='System Regis IV')
        self.set_default_size(1080, 700)
        self.set_size_request(920, 620)
        self.get_style_context().add_class('regis')
        self.set_icon_from_file(str(BASE / 'assets/regis.svg'))
        self.registry = registry
        self.preview = preview
        self.selected = registry.users[0] if registry.users else None
        self.finger = 'right-index-finger'
        self.dialog = None
        self.closing = False
        self.rebuilding = False
        header = Gtk.HeaderBar(title='SYSTEM REGIS IV', show_close_button=True)
        header.set_subtitle('Fingeravtrycksregistret')
        self.set_titlebar(header)
        self.connect('delete-event', self.on_close)
        layout = box(False)
        self.add(layout)
        sidebar = box(spacing=20, css='sidebar')
        sidebar.set_size_request(248, -1)
        layout.pack_start(sidebar, False, False, 0)
        crest = Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(str(BASE / 'assets/regis.svg'), 74, 74, True))
        crest.set_halign(Gtk.Align.START)
        sidebar.pack_start(crest, False, False, 0)
        brand = box(spacing=5)
        brand.pack_start(label('SYSTEM', 'eyebrow'), False, False, 0)
        brand.pack_start(label('Regis IV', 'brand'), False, False, 0)
        brand.pack_start(label('SIGILL • IDENTITET • TILLIT', 'dim'), False, False, 0)
        sidebar.pack_start(brand, False, False, 0)
        sidebar.pack_start(Gtk.Separator(), False, False, 0)
        sidebar.pack_start(label('ANVÄNDARE', 'eyebrow'), False, False, 0)
        self.user_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.user_list.get_style_context().add_class('users')
        self.user_list.connect('row-selected', self.select_user)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.user_list)
        sidebar.pack_start(scroll, True, True, 0)
        self.all_button = button('Läs alla register', lambda *_: registry.refresh(), 'quiet')
        self.all_button.set_tooltip_text('Hämta registrerade fingrar för lokala användare. Administratörsbehörighet kan behövas.')
        sidebar.pack_start(self.all_button, False, False, 0)
        sidebar.pack_start(label('Andras register kräver\nadministratörens behörighet.', 'dim'), False, False, 0)
        sidebar.pack_start(label('EUTHER / VFS491\nDEBIAN · LOKALT REGISTER', 'dim'), False, False, 0)
        content_scroll = Gtk.ScrolledWindow()
        content_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        layout.pack_start(content_scroll, True, True, 0)
        content = box(spacing=16)
        content.set_border_width(24)
        content_scroll.add(content)
        hero = box(False, 20, 'hero')
        titles = box(spacing=8)
        titles.pack_start(label('DET PERSONLIGA SIGILLET', 'eyebrow'), False, False, 0)
        titles.pack_start(label('Din identitet. Ditt sigill.', 'title'), False, False, 0)
        titles.pack_start(label('Ett fingeravtryck. En tydlig tillhörighet.', 'subtitle'), False, False, 0)
        hero.pack_start(titles, True, True, 0)
        hero.pack_end(label('IV', 'seal'), False, False, 0)
        content.pack_start(hero, False, False, 0)
        top = box(False, 12)
        user_title = box(spacing=5)
        self.user_heading = label('', 'user-title')
        self.user_subtitle = label('', 'muted')
        user_title.pack_start(self.user_heading, False, False, 0)
        user_title.pack_start(self.user_subtitle, False, False, 0)
        top.pack_start(user_title, True, True, 0)
        self.connection = label('Ansluter …', 'status')
        self.connection.set_valign(Gtk.Align.CENTER)
        top.pack_end(self.connection, False, False, 0)
        content.pack_start(top, False, False, 0)
        self.tiles = {}
        for side, title in [('right', 'HÖGER HAND'), ('left', 'VÄNSTER HAND')]:
            section = box(spacing=9)
            section.pack_start(label(title, 'section'), False, False, 0)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9, homogeneous=True)
            for finger, name in FINGERS:
                if not finger.startswith(side):
                    continue
                tile = Gtk.Button()
                tile.get_style_context().add_class('finger')
                inner = box(spacing=4)
                icon = label('◎', 'finger-icon')
                icon.set_xalign(.5)
                text = label(name.split(' ', 1)[1].capitalize(), 'finger-title')
                text.set_xalign(.5)
                status = label('', 'finger-state')
                status.set_xalign(.5)
                inner.pack_start(icon, False, False, 0)
                inner.pack_start(text, False, False, 0)
                inner.pack_start(status, False, False, 0)
                tile.add(inner)
                tile.connect('clicked', lambda _button, f=finger: self.select_finger(f))
                self.tiles[finger] = (tile, status)
                row.pack_start(tile, True, True, 0)
            section.pack_start(row, False, False, 0)
            content.pack_start(section, False, False, 0)
        detail = box(spacing=15, css='detail')
        self.finger_heading = label('', 'user-name')
        self.finger_description = label('', 'muted', True)
        detail.pack_start(self.finger_heading, False, False, 0)
        detail.pack_start(self.finger_description, False, False, 0)
        actions = box(False, 10)
        self.enroll_button = button('Registrera finger', lambda *_: self.begin('enroll'), 'primary')
        self.verify_button = button('Verifiera', lambda *_: self.begin('verify'))
        self.delete_button = button('Radera', self.confirm_delete, 'danger')
        actions.pack_start(self.enroll_button, False, False, 0)
        actions.pack_start(self.verify_button, False, False, 0)
        actions.pack_end(self.delete_button, False, False, 0)
        detail.pack_start(actions, False, False, 0)
        content.pack_start(detail, False, False, 0)
        footer = box(False, 12)
        self.message = label('', 'notice', True)
        self.message.set_max_width_chars(65)
        footer.pack_start(self.message, True, True, 0)
        self.refresh_button = button('Uppdatera', self.refresh, 'quiet')
        footer.pack_end(self.refresh_button, False, False, 0)
        content.pack_start(footer, False, False, 0)
        if preview:
            content.pack_start(label('FÖRHANDSVISNING · inga systemändringar', 'eyebrow'), False, False, 0)
        registry.connect('changed', lambda *_: self.render())
        self.render()
        self.show_all()

    def render(self):
        r = self.registry
        self.rebuilding = True
        for child in self.user_list.get_children():
            self.user_list.remove(child)
        for user in r.users:
            row = Gtk.ListBoxRow()
            row.user = user
            content = box(False, 10)
            avatar = label(user['name'][:2].upper(), 'avatar')
            avatar.set_valign(Gtk.Align.CENTER)
            content.pack_start(avatar, False, False, 0)
            info = box(spacing=4)
            info.pack_start(label(user['name'], 'user-name'), False, False, 0)
            count = user['fingers']
            text = ('Kunde inte hämtas' if user.get('error') else 'Ej hämtat') if count is None else ('1 registrerat finger' if len(count) == 1 else f'{len(count)} registrerade fingrar')
            info.pack_start(label(text, 'dim'), False, False, 0)
            content.pack_start(info, True, True, 0)
            row.add(content)
            self.user_list.add(row)
            if self.selected is user:
                self.user_list.select_row(row)
        self.user_list.show_all()
        self.rebuilding = False
        self.user_list.set_sensitive(not r.busy)
        self.all_button.set_sensitive(not r.busy and r.device is not None and not self.preview)
        self.refresh_button.set_sensitive(not r.busy and not self.preview)
        self.connection.set_text('LÄSAREN ANSLUTEN' if r.device else 'EJ ANSLUTEN')
        (self.connection.get_style_context().remove_class if r.device else self.connection.get_style_context().add_class)('offline')
        self.refresh_button.set_label('Uppdatera' if r.device else 'Anslut')
        self.message.set_text(r.message)
        if not self.selected:
            return
        user = self.selected
        self.user_heading.set_text(user['label'])
        count = user['fingers']
        self.user_subtitle.set_text('@' + user['name'] + '  /  ' + ('Register ej hämtat' if count is None else f'{len(count)} av 10 fingrar registrerade'))
        for finger, (tile, state) in self.tiles.items():
            registered = count is not None and finger in count
            context = tile.get_style_context()
            for css, active in [('enrolled', registered), ('selected', finger == self.finger)]:
                (context.add_class if active else context.remove_class)(css)
            state.set_text('Ej hämtat' if count is None else ('Registrerat' if registered else 'Ledigt'))
            tile.set_sensitive(not r.busy)
            tile.set_tooltip_text(FINGER_NAMES[finger] + ': ' + state.get_text())
        registered = count is not None and self.finger in count
        available = not r.busy and r.device is not None and count is not None and not self.preview
        self.enroll_button.set_sensitive(available and not registered)
        self.verify_button.set_sensitive(available and registered)
        self.delete_button.set_sensitive(available and registered)
        self.finger_heading.set_text(FINGER_NAMES[self.finger])
        self.finger_description.set_text('Hämta användarens register för att hantera fingrar.' if count is None else
            ('Registrerat sigill. Verifiera avtrycket eller radera just detta finger.' if registered else
             'Välj Registrera finger. Du guidas genom varje svep.'))

    def select_user(self, _list, row):
        if self.rebuilding or not row:
            return
        self.selected = row.user
        self.render()
        if self.selected['fingers'] is None and not self.preview:
            self.registry.refresh([self.selected])

    def select_finger(self, finger):
        self.finger = finger
        self.render()

    def refresh(self, *_):
        if self.registry.device:
            self.registry.refresh([self.selected] if self.selected else [])
        else:
            self.registry.connect_device()

    def confirm_delete(self, *_):
        user, finger = self.selected, self.finger
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.NONE, text='Radera detta fingeravtryck?')
        dialog.get_style_context().add_class('dialog')
        detail = f"{FINGER_NAMES[finger]} för {user['name']} tas bort. Det måste registreras på nytt för att användas igen."
        if len(user['fingers'] or []) == 1:
            detail += '\n\nDetta är användarens sista registrerade finger. Lösenordet påverkas inte.'
        dialog.format_secondary_text(detail)
        dialog.add_button('Behåll', Gtk.ResponseType.CANCEL)
        danger = dialog.add_button('Radera finger', Gtk.ResponseType.ACCEPT)
        danger.get_style_context().add_class('danger')
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        def response(widget, choice):
            widget.destroy()
            if choice == Gtk.ResponseType.ACCEPT:
                self.begin('delete')
        dialog.connect('response', response)
        dialog.show_all()

    def begin(self, mode):
        user, finger = self.selected, self.finger
        dialog = Gtk.Dialog(title={'enroll': 'Registrera ett nytt sigill', 'verify': 'Verifiera ditt sigill', 'delete': 'Radera finger'}[mode],
                            transient_for=self, modal=True)
        dialog.set_default_size(570, 380)
        dialog.get_style_context().add_class('dialog')
        area = dialog.get_content_area()
        area.set_spacing(18)
        area.set_border_width(30)
        area.pack_start(label('SYSTEM REGIS IV  /  ' + user['name'].upper(), 'eyebrow'), False, False, 0)
        emblem = Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(str(BASE / 'assets/regis.svg'), 65, 65, True))
        emblem.set_halign(Gtk.Align.START)
        area.pack_start(emblem, False, False, 0)
        title = label('Redo när du är', 'progress-title', True)
        title.set_max_width_chars(32)
        detail = label('Valt finger: ' + FINGER_NAMES[finger] + '.\nHåll fingret borta tills du får en uppmaning.', 'subtitle', True)
        detail.set_max_width_chars(55)
        area.pack_start(title, False, False, 0)
        area.pack_start(detail, False, False, 0)
        progress = Gtk.ProgressBar()
        area.pack_start(progress, False, False, 0)
        cancel = dialog.add_button('Avbryt', Gtk.ResponseType.CANCEL)
        start = dialog.add_button('Börja' if mode != 'delete' else 'Utför radering', Gtk.ResponseType.ACCEPT)
        start.get_style_context().add_class('primary')
        state = {'started': False, 'finished': False}
        self.dialog = dialog
        def event(headline, description, fraction):
            title.set_text(headline)
            detail.set_text(description)
            progress.set_fraction(fraction)
        def done(success, message):
            state['finished'] = True
            title.set_text('Sigillet är klart' if success else 'Åtgärden avslutad')
            title.get_style_context().add_class('success' if success else 'failure')
            detail.set_text(message)
            progress.set_fraction(1 if success else 0)
            cancel.set_label('Stäng')
            cancel.set_sensitive(True)
            start.hide()
            if self.closing:
                dialog.destroy()
                self.get_application().quit()
            elif user['fingers'] is None:
                self.registry.refresh([user])
        def response(widget, choice):
            if state['finished'] or not state['started'] and choice != Gtk.ResponseType.ACCEPT:
                self.dialog = None
                widget.destroy()
                return
            if choice == Gtk.ResponseType.ACCEPT and not state['started']:
                state['started'] = True
                start.hide()
                try:
                    self.registry.start(mode, user, finger, event, done)
                except (RuntimeError, ValueError) as error:
                    done(False, str(error))
            elif state['started']:
                cancel.set_sensitive(False)
                self.registry.cancel()
        dialog.connect('response', response)
        dialog.connect('delete-event', lambda *_: (response(dialog, Gtk.ResponseType.CANCEL), True)[1])
        dialog.show_all()
        if mode == 'delete':
            response(dialog, Gtk.ResponseType.ACCEPT)  # User already confirmed exact target.

    def on_close(self, *_):
        if self.registry.job:
            self.closing = True
            self.registry.cancel()
            return True
        return False


class App(Gtk.Application):
    def __init__(self, preview_path=None):
        super().__init__(application_id='se.euther.SystemRegisIV',
                         flags=Gio.ApplicationFlags.NON_UNIQUE if preview_path else Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.preview_path = preview_path

    def do_activate(self):
        if self.get_active_window():
            self.get_active_window().present()
            return
        css = Gtk.CssProvider()
        css.load_from_path(str(BASE / 'style.css'))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        registry = Registry()
        if self.preview_path:
            registry.users = [dict(name='nichlase', label='Nichlas', uid=1000, fingers=['right-index-finger'], error=None),
                              dict(name='root', label='Administratör', uid=0, fingers=None, error=None)]
            registry.device = object()
            registry.message = 'Dina avtryck stannar i datorns skyddade register.'
        window = RegisWindow(self, registry, bool(self.preview_path))
        window.present()
        if self.preview_path:
            def capture():
                try:
                    width, height = window.get_allocated_width(), window.get_allocated_height()
                    picture = Gdk.pixbuf_get_from_window(window.get_window(), 0, 0, width, height)
                    if picture is None:
                        raise RuntimeError('Run preview with GDK_BACKEND=x11')
                    picture.savev(self.preview_path, 'png', [], [])
                finally:
                    self.quit()
                return False
            GLib.timeout_add(900, capture)
        else:
            registry.connect_device()


def main():
    import argparse
    GLib.set_prgname('se.euther.SystemRegisIV')
    GLib.set_application_name('System Regis IV')
    Gdk.set_program_class('se.euther.SystemRegisIV')
    Gtk.Window.set_default_icon_name('se.euther.SystemRegisIV')
    parser = argparse.ArgumentParser(description='System Regis IV — fingeravtrycksregistret')
    parser.add_argument('--preview', metavar='PNG', help='Render an explicitly marked sample, without fprintd access')
    args = parser.parse_args()
    return App(args.preview).run([sys.argv[0]])

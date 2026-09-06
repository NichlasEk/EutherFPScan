import QtQuick
import QtQuick.Controls

Button {
    id: control
    property bool primary: false
    implicitHeight: 46
    font.pixelSize: 14
    contentItem: Text {
        text: control.text
        font: control.font
        color: !control.enabled ? "#82909e" : control.primary ? "#101b29" : "#e6e8e9"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: 8
        color: !control.enabled ? "#1b2735" : control.primary ? (control.hovered ? "#e4cd94" : "#d0b87d") : (control.hovered ? "#24364b" : "#152333")
        border.color: control.activeFocus ? "#72d7d5" : control.primary ? "#e2c990" : "#354357"
        border.width: control.activeFocus ? 2 : 1
    }
}

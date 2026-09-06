import QtQuick
import QtQuick.Controls

TextField {
    id: field
    implicitHeight: 44
    color: "#e6e8e9"
    placeholderTextColor: "#8f9ba9"
    selectionColor: "#346466"
    font.pixelSize: 14
    leftPadding: 14
    background: Rectangle {
        color: "#0d1622"; radius: 8
        border.color: field.activeFocus ? "#72d7d5" : "#354357"
        border.width: field.activeFocus ? 2 : 1
    }
}

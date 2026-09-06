import QtQuick
import QtQuick.Controls

ComboBox {
    id: box
    implicitHeight: 44
    font.pixelSize: 13
    palette.text: "#e6e8e9"
    palette.buttonText: "#e6e8e9"
    palette.base: "#0d1622"
    palette.window: "#152333"
    palette.button: "#152333"
    palette.highlight: "#346466"
    palette.highlightedText: "#ffffff"
    background: Rectangle {
        color: "#0d1622"; radius: 8
        border.color: box.activeFocus ? "#72d7d5" : "#354357"
        border.width: box.activeFocus ? 2 : 1
    }
}

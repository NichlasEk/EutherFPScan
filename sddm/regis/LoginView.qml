import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    width: 1366
    height: 768
    color: "#090f18"
    property bool fingerprintEnabled: false
    property bool busy: false
    property bool succeeded: false
    property bool disconnected: false
    property string notice: ""
    property string host: ""
    property string initialUser: ""
    property var users
    property var sessions
    property int initialSession: 0
    signal submitted(string user, string password, int session)

    function submit(fingerprint) {
        if (busy || succeeded || disconnected || username.editText.trim() === "" || session.currentIndex < 0)
            return;
        busy = true;
        notice = fingerprint ? "Startar fingerkontrollen. Följ läsarens uppmaning." :
                 fingerprintEnabled ? "Kontrollerar inloggningen. Lösenordet används efter fingerkontrollen." : "Kontrollerar lösenordet…";
        const secret = fingerprint ? "" : password.text;
        password.clear();
        submitted(username.editText.trim(), secret, session.currentIndex);
    }
    function failed() {
        busy = false;
        succeeded = false;
        notice = "Inloggningen lyckades inte. Försök igen eller använd ditt lösenord.";
        password.forceActiveFocus();
    }
    function accepted() {
        succeeded = true;
        busy = false;
        notice = "Inloggningen godkänd. Öppnar skrivbordet…";
    }

    // Vector decoration, intentionally quiet behind the login controls.
    Canvas {
        anchors.fill: parent
        onPaint: {
            const c = getContext("2d");
            c.clearRect(0, 0, width, height);
            c.strokeStyle = "#1b3445";
            c.lineWidth = 1;
            for (let i = 0; i < 7; ++i) {
                const x = 45 + i * 28;
                c.beginPath(); c.moveTo(x, height); c.lineTo(x, height * .64 - i * 19);
                c.lineTo(x + 110, height * .64 - i * 19 - 110);
                c.lineTo(width * .34, height * .64 - i * 19 - 110); c.stroke();
            }
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }
    Row {
        anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 32
        spacing: 12
        Image { source: "regis.svg"; width: 40; height: 40 }
        Column {
            Text { text: "SYSTEM REGIS IV"; color: "#d0b87d"; font.pixelSize: 13; font.letterSpacing: 2 }
            Text { text: "En personlig ingång"; color: "#8f9ba9"; font.pixelSize: 12 }
        }
    }
    Text {
        anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 36
        text: root.host; color: "#8f9ba9"; font.pixelSize: 12
    }
    Rectangle {
        anchors.centerIn: parent
        width: Math.min(456, parent.width - 40)
        height: content.implicitHeight + 48
        radius: 18; color: "#101b29"; border.color: "#354250"
        ColumnLayout {
            id: content
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
            anchors.margins: 24
            spacing: 12
            Text {
                text: root.succeeded ? "Välkommen in" : "Välkommen tillbaka"
                color: "#eee5cd"; font.family: "Liberation Serif"; font.pixelSize: 32
                Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter
            }
            Text {
                text: root.fingerprintEnabled ? "Ditt finger. Din ingång." : "Logga in på ditt skrivbord."
                color: "#a5b1c0"; font.pixelSize: 13
                Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter
            }
            RegisCombo {
                id: username
                Layout.fillWidth: true
                model: root.users; textRole: "name"; editable: true
                currentIndex: -1
                Component.onCompleted: editText = root.initialUser
                enabled: !root.busy && !root.succeeded && !root.disconnected
                Accessible.name: "Användarnamn, välj eller skriv ett konto"
                onEditTextChanged: { password.clear(); root.notice = ""; }
            }
            RegisButton {
                Layout.fillWidth: true
                visible: root.fingerprintEnabled
                text: root.busy ? "Kontroll pågår…" : "Logga in med fingeravtryck"
                primary: true
                enabled: !root.busy && !root.succeeded && !root.disconnected && username.editText.trim() !== "" && session.currentIndex >= 0
                onClicked: root.submit(true)
            }
            Rectangle {
                Layout.fillWidth: true; implicitHeight: statusText.implicitHeight + 24
                color: root.succeeded ? "#112e32" : "#152333"; radius: 8
                border.color: root.succeeded ? "#346466" : "#293e50"
                Text {
                    id: statusText
                    anchors.fill: parent; anchors.margins: 12
                    text: root.notice || (root.fingerprintEnabled ? "Tryck på knappen och svep sedan ett registrerat finger." : "Ange ditt användarnamn och lösenord.")
                    textFormat: Text.PlainText; wrapMode: Text.WordWrap
                    color: root.succeeded ? "#7cd9c9" : "#bacbd8"; font.pixelSize: 13
                    Accessible.role: Accessible.StaticText
                    Accessible.name: text
                }
            }
            RegisField {
                id: password
                Layout.fillWidth: true; placeholderText: "Lösenord"; echoMode: TextInput.Password
                enabled: !root.busy && !root.succeeded && !root.disconnected
                Accessible.name: "Lösenord"
                onAccepted: root.submit(false)
            }
            RegisButton {
                Layout.fillWidth: true; text: "Logga in med lösenord"
                primary: !root.fingerprintEnabled
                enabled: !root.busy && !root.succeeded && !root.disconnected && username.editText.trim() !== "" && password.text.length > 0 && session.currentIndex >= 0
                onClicked: root.submit(false)
            }
            Text {
                visible: root.fingerprintEnabled
                text: "Lösenordsinloggning kan ta cirka 15 sekunder extra medan fingerkontrollen avslutas."
                color: "#9caabb"; font.pixelSize: 11
                Layout.fillWidth: true; wrapMode: Text.WordWrap
            }
            RegisCombo {
                id: session
                Layout.fillWidth: true; model: root.sessions; textRole: "name"
                currentIndex: root.initialSession
                enabled: !root.busy && !root.succeeded && !root.disconnected
                Accessible.name: "Skrivbordssession"
            }
        }
    }
    Text {
        anchors.bottom: parent.bottom; anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottomMargin: 20
        text: "SYSTEM REGIS IV  /  EUTHER"
        color: "#708093"; font.pixelSize: 10; font.letterSpacing: 3
    }
}

import QtQuick
import QtQuick.Controls

LoginView {
    id: view
    host: "HP ProBook 4340s"
    initialUser: "test-user"
    fingerprintEnabled: true
    users: ListModel { ListElement { name: "test-user" } }
    sessions: ListModel { ListElement { name: "Plasma (Wayland)" } }
    property int step: 0
    onSubmitted: (user, password, session) => { step = 0; simulation.start(); }
    Timer {
        id: simulation
        interval: 1400; repeat: true
        onTriggered: {
            view.step++;
            if (view.step === 1) view.notice = "Svep höger pekfinger över fingeravtrycksläsaren.";
            else {
                stop();
                if (outcome.currentIndex === 0) view.accepted();
                else if (outcome.currentIndex === 1) view.failed();
                else { view.failed(); view.notice = "Ingen läsare tillgänglig. Försök med lösenord."; }
            }
        }
    }
    Row {
        anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.margins: 16
        spacing: 8
        RegisCombo {
            id: outcome
            model: ["Demo: godkänd", "Demo: misslyckad", "Demo: läsare saknas"]
            enabled: !view.busy
        }
        RegisButton {
            text: "Börja om"; enabled: !view.busy
            onClicked: { view.succeeded = false; view.notice = ""; }
        }
    }
    Text {
        anchors.top: parent.top; anchors.horizontalCenter: parent.horizontalCenter; anchors.topMargin: 36
        text: "FÖRHANDSVISNING · SIMULERADE RESULTAT"
        color: "#7cd9c9"; font.pixelSize: 11
    }
    Timer {
        interval: 700; running: String(config.screenshotPath || "") !== ""
        onTriggered: view.grabToImage(function(result) {
            if (!result.saveToFile(String(config.screenshotPath))) console.error("PREVIEW_CAPTURE_FAILED");
            else console.log("PREVIEW_CAPTURE_OK");
            Qt.quit();
        })
    }
}

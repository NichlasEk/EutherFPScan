import QtQuick

LoginView {
    id: view
    host: sddm.hostName
    initialUser: userModel.lastUser
    users: userModel
    sessions: sessionModel
    initialSession: sessionModel.lastIndex
    fingerprintEnabled: String(config.fingerprintEnabled) === "true"
    onSubmitted: (user, password, session) => sddm.login(user, password, session)
    Connections {
        target: sddm
        function onInformationMessage(message) { view.notice = message; }
        function onLoginFailed() { view.failed(); }
        function onLoginSucceeded() { view.accepted(); }
        function onSocketDisconnected() {
            view.disconnected = true;
            view.notice = "Anslutningen till inloggningstjänsten bröts.";
        }
    }
}

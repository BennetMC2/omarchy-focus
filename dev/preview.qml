import QtQuick
import QtQuick.Window
import Quickshell
import qs.Commons

Window {
  id: window
  width: Number(Quickshell.env("FOCUS_PREVIEW_WIDTH")) || 468; height: 628; visible: true
  color: Color.popups.background
  title: "Bouncer preview — disposable data"
  property string previewPage: Quickshell.env("FOCUS_PREVIEW_PAGE") || "today"
  Item {
    id: canvas
    anchors.fill: parent
    Rectangle { anchors.fill: parent; color: Color.popups.background; border.color: Color.accent; border.width: 1 }
    FocusCard { id: card; anchors.fill: parent; anchors.margins: 24; service: fixture; active: true; page: window.previewPage }
  }
  QtObject {
    id: fixture
    property var state: ({
      setup:true, started:false, recovered:false, locked:true, total:5, completed:2, streak:3,
      tasks:[
        {id:"1",text:"Send the release note to the team",main:true,status:"open"},
        {id:"2",text:"Call the dentist",main:false,status:"open"},
        {id:"3",text:"Review the draft for Friday",main:false,status:"open"},
        {id:"4",text:"Reply to Alex",main:false,status:"passed",note:"Message sent.",basis:"claim"},
        {id:"5",text:"Book the train",main:false,status:"passed",note:"Booking confirmed.",basis:"evidence"}
      ],
      settings:{strictness:"standard",planning:"quick",provider:"claude",sites:["youtube.com","reddit.com","x.com"],apps:["Discord"],roots:[],mode:"all",reset:"04:00"},
      pending:{}, carry:[], overrides:[],
      backend:{provider:"claude",model:"haiku",label:"Claude (haiku), on Anthropic's servers",ok:true,auto:false}
    })
    property var chat: ({messages:[{role:"user",text:"Add those three tasks."},{role:"agent",text:"Added."}],busy:false,suggestion:"",choices:null,consent:null,streaming:""})
    property real clock: Date.now()/1000
    property string error: ""
    signal submissionFinished(string id, bool ok, string message)
    property bool connected: true
    property bool replyOk: true
    property var lastCommand: ({})
    function send(command) {
      lastCommand = command
      if (!connected) return false
      if (command.requestId) Qt.callLater(function() { submissionFinished(command.requestId, replyOk, replyOk ? "" : "Test refusal") })
      return true
    }
    function close() {}
  }
  Timer {
    interval: 100; running: Quickshell.env("FOCUS_PREVIEW_CHECK") === "1"
    onTriggered: {
      function check(value, message) { if (!value) { console.error("UI CHECK FAILED:",message); Qt.exit(2) } }
      card.adding = true; card.prompt.text = "First task\nSecond task"
      fixture.connected = false; card.submit()
      check(card.prompt.text.length > 0 && !card.sending, "Disconnected input was lost")
      fixture.connected = true; fixture.replyOk = false; card.submit()
      var originalId = card.requestId
      Qt.callLater(function() {
        check(!card.sending && card.prompt.text.length > 0 && card.inputError === "Test refusal", "Refused input was lost")
        fixture.replyOk = true; card.submit()
        check(fixture.lastCommand.requestId === originalId && fixture.lastCommand.op === "capture", "Retry id changed")
        Qt.callLater(function() {
          check(card.prompt.text === "" && !card.sending && !card.requestId, "Confirmed submission did not clear")
          check(fixture.lastCommand.text === "First task\nSecond task", "Multiline task input changed")
          card.adding = false
          card.page = "settings"; card.prompt.text = "hello"; card.submit()
          check(card.page === "today" && fixture.lastCommand.op === "say", "Chat from Settings stayed hidden")
          Qt.callLater(function() {
            check(card.prompt.text === "" && !card.sending, "Chat submission did not finish")
            console.log("UI CHECKS PASSED")
          })
        })
      })
    }
  }
  Timer {
    property int frame: 0
    interval: 700; repeat: true; running: Quickshell.env("FOCUS_PREVIEW_DEMO") === "1"
    onTriggered: {
      if (frame === 1) { card.adding = true; card.prompt.text = "Read the release checklist" }
      if (frame === 2) {
        card.submit()
        var next = JSON.parse(JSON.stringify(fixture.state))
        next.tasks.push({id:"6",text:"Read the release checklist",status:"open",main:false})
        next.total = next.tasks.length; fixture.state = next
      }
      if (frame === 3) {
        card.adding = false
        var started = JSON.parse(JSON.stringify(fixture.state))
        started.started = true; fixture.state = started
      }
      if (frame === 4) { card.showDone = true }
      if (frame === 5) card.page = "settings"
      if (frame === 6) card.page = "history"
      var index = frame
      Qt.callLater(function() {
        canvas.grabToImage(function(result) {
          result.saveToFile(Quickshell.env("FOCUS_PREVIEW_OUTPUT") + "/frame-0" + index + ".png")
          if (index === 6) Qt.quit()
        })
      })
      frame++
    }
  }
  Timer {
    interval: 1800; running: Quickshell.env("FOCUS_PREVIEW_DEMO") !== "1"
    onTriggered: {
      canvas.grabToImage(function(result) {
        var path = Quickshell.env("FOCUS_PREVIEW_OUTPUT")
        console.log("Saved", result.saveToFile(path), path)
        Qt.quit()
      })
    }
  }
}

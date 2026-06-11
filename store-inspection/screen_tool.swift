import Foundation
import CoreGraphics
import AppKit

func usage() -> Never {
    FileHandle.standardError.write("用法：screen_tool.swift info | click x y | scroll amount | key name | text value\n".data(using: .utf8)!)
    exit(2)
}

func postKey(_ keyCode: CGKeyCode, flags: CGEventFlags = []) {
    let source = CGEventSource(stateID: .hidSystemState)
    let down = CGEvent(keyboardEventSource: source, virtualKey: keyCode, keyDown: true)
    let up = CGEvent(keyboardEventSource: source, virtualKey: keyCode, keyDown: false)
    down?.flags = flags
    up?.flags = flags
    down?.post(tap: .cghidEventTap)
    usleep(90_000)
    up?.post(tap: .cghidEventTap)
}

func keyCodeFor(_ key: String) -> CGKeyCode? {
    switch key.lowercased() {
    case "0": return 29
    case "1": return 18
    case "2": return 19
    case "3": return 20
    case "4": return 21
    case "5": return 23
    case "6": return 22
    case "7": return 26
    case "8": return 28
    case "9": return 25
    case "a": return 0
    default: return nil
    }
}

let args = CommandLine.arguments
if args.count < 2 {
    usage()
}

switch args[1] {
case "info":
    guard let screen = NSScreen.main else {
        FileHandle.standardError.write("无法读取屏幕信息\n".data(using: .utf8)!)
        exit(1)
    }
    let frame = screen.frame
    let scale = screen.backingScaleFactor
    let result: [String: Any] = [
        "width": frame.width,
        "height": frame.height,
        "scale": scale
    ]
    let data = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write("\n".data(using: .utf8)!)

case "click":
    guard args.count >= 4, let x = Double(args[2]), let y = Double(args[3]) else {
        usage()
    }
    let point = CGPoint(x: x, y: y)
    let source = CGEventSource(stateID: .hidSystemState)
    let down = CGEvent(mouseEventSource: source, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left)
    let up = CGEvent(mouseEventSource: source, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left)
    down?.post(tap: .cghidEventTap)
    usleep(90_000)
    up?.post(tap: .cghidEventTap)

case "scroll":
    guard args.count >= 3, let amount = Int32(args[2]) else {
        usage()
    }
    let source = CGEventSource(stateID: .hidSystemState)
    let event = CGEvent(scrollWheelEvent2Source: source, units: .pixel, wheelCount: 1, wheel1: amount, wheel2: 0, wheel3: 0)
    event?.post(tap: .cghidEventTap)

case "key":
    guard args.count >= 3 else {
        usage()
    }
    let key = args[2].lowercased()
    let keyCode: CGKeyCode
    var flags = CGEventFlags()
    switch key {
    case "backspace", "delete":
        keyCode = 51
    case "cmda":
        keyCode = 0
        flags = .maskCommand
    case "pagedown":
        keyCode = 121
    case "pageup":
        keyCode = 116
    case "home":
        keyCode = 115
    case "end":
        keyCode = 119
    case "escape", "esc":
        keyCode = 53
    case "cmdminus":
        keyCode = 27
        flags = .maskCommand
    case "cmdplus":
        keyCode = 24
        flags = .maskCommand
    case "cmd0":
        keyCode = 29
        flags = .maskCommand
    default:
        if let code = keyCodeFor(key) {
            keyCode = code
        } else {
            usage()
        }
    }
    postKey(keyCode, flags: flags)

case "text":
    guard args.count >= 3 else {
        usage()
    }
    for char in args[2] {
        guard let code = keyCodeFor(String(char)) else {
            usage()
        }
        postKey(code)
        usleep(60_000)
    }

default:
    usage()
}

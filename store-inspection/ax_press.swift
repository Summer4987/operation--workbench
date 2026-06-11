import ApplicationServices
import AppKit
import Foundation

func usage() -> Never {
    FileHandle.standardError.write("用法：ax_press.swift <AppName> <Text> [minY]\n".data(using: .utf8)!)
    exit(2)
}

func stringValue(_ value: CFTypeRef?) -> String {
    guard let value else { return "" }
    if CFGetTypeID(value) == CFStringGetTypeID() {
        return value as! String
    }
    if CFGetTypeID(value) == CFNumberGetTypeID() {
        return "\(value)"
    }
    return ""
}

func attr(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    let error = AXUIElementCopyAttributeValue(element, name as CFString, &value)
    return error == .success ? value : nil
}

func pointValue(_ value: CFTypeRef?) -> CGPoint? {
    guard let value, CFGetTypeID(value) == AXValueGetTypeID() else { return nil }
    var point = CGPoint.zero
    return AXValueGetValue(value as! AXValue, .cgPoint, &point) ? point : nil
}

func children(_ element: AXUIElement) -> [AXUIElement] {
    guard let value = attr(element, kAXChildrenAttribute as String) else { return [] }
    return (value as? [AXUIElement]) ?? []
}

func text(_ element: AXUIElement) -> String {
    for name in [kAXTitleAttribute, kAXValueAttribute, kAXDescriptionAttribute, kAXHelpAttribute] {
        let value = stringValue(attr(element, name as String)).trimmingCharacters(in: .whitespacesAndNewlines)
        if !value.isEmpty {
            return value
        }
    }
    return ""
}

func press(_ element: AXUIElement) -> Bool {
    AXUIElementPerformAction(element, kAXPressAction as CFString) == .success
}

func search(_ element: AXUIElement, target: String, minY: Double, parent: AXUIElement?) -> Bool {
    let value = text(element)
    let position = pointValue(attr(element, kAXPositionAttribute as String))
    if value == target && (position == nil || Double(position!.y) >= minY) {
        if press(element) { return true }
        if let parent, press(parent) { return true }
    }
    for child in children(element) {
        if search(child, target: target, minY: minY, parent: element) {
            return true
        }
    }
    return false
}

let args = CommandLine.arguments
if args.count < 3 {
    usage()
}

let appName = args[1]
let target = args[2]
let minY = args.count >= 4 ? (Double(args[3]) ?? 0) : 0
let apps = NSWorkspace.shared.runningApplications.filter {
    ($0.localizedName ?? "").localizedCaseInsensitiveContains(appName)
}
guard let app = apps.first else {
    FileHandle.standardError.write("没有找到运行中的应用：\(appName)\n".data(using: .utf8)!)
    exit(1)
}

let appElement = AXUIElementCreateApplication(app.processIdentifier)
guard let windowsValue = attr(appElement, kAXWindowsAttribute as String),
      let windows = windowsValue as? [AXUIElement],
      let frontWindow = windows.first(where: { stringValue(attr($0, kAXTitleAttribute as String)).contains("店铺推广") }) ?? windows.first else {
    FileHandle.standardError.write("没有找到窗口：\(appName)\n".data(using: .utf8)!)
    exit(1)
}

if search(frontWindow, target: target, minY: minY, parent: nil) {
    print("pressed")
    exit(0)
}

FileHandle.standardError.write("没有找到可按下元素：\(target)\n".data(using: .utf8)!)
exit(1)

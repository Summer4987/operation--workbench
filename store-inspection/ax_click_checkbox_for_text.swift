import ApplicationServices
import AppKit
import Foundation

func usage() -> Never {
    FileHandle.standardError.write("用法：ax_click_checkbox_for_text.swift <AppName> <RowText>\n".data(using: .utf8)!)
    exit(2)
}

func stringValue(_ value: CFTypeRef?) -> String {
    guard let value else { return "" }
    if CFGetTypeID(value) == CFStringGetTypeID() { return value as! String }
    if CFGetTypeID(value) == CFNumberGetTypeID() { return "\(value)" }
    return ""
}

func attr(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    return AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success ? value : nil
}

func pointValue(_ value: CFTypeRef?) -> CGPoint? {
    guard let value, CFGetTypeID(value) == AXValueGetTypeID() else { return nil }
    var point = CGPoint.zero
    return AXValueGetValue(value as! AXValue, .cgPoint, &point) ? point : nil
}

func sizeValue(_ value: CFTypeRef?) -> CGSize? {
    guard let value, CFGetTypeID(value) == AXValueGetTypeID() else { return nil }
    var size = CGSize.zero
    return AXValueGetValue(value as! AXValue, .cgSize, &size) ? size : nil
}

func children(_ element: AXUIElement) -> [AXUIElement] {
    guard let value = attr(element, kAXChildrenAttribute as String) else { return [] }
    return (value as? [AXUIElement]) ?? []
}

func visibleText(_ element: AXUIElement) -> String {
    for name in [kAXTitleAttribute, kAXValueAttribute, kAXDescriptionAttribute, kAXHelpAttribute] {
        let value = stringValue(attr(element, name as String)).trimmingCharacters(in: .whitespacesAndNewlines)
        if !value.isEmpty { return value }
    }
    return ""
}

func collect(_ element: AXUIElement, _ rows: inout [(element: AXUIElement, role: String, text: String, x: Double, y: Double, w: Double, h: Double)]) {
    let role = stringValue(attr(element, kAXRoleAttribute as String))
    let text = visibleText(element)
    let point = pointValue(attr(element, kAXPositionAttribute as String)) ?? .zero
    let size = sizeValue(attr(element, kAXSizeAttribute as String)) ?? .zero
    rows.append((element, role, text, Double(point.x), Double(point.y), Double(size.width), Double(size.height)))
    for child in children(element) {
        collect(child, &rows)
    }
}

let args = CommandLine.arguments
if args.count < 3 { usage() }

let appName = args[1]
let rowText = args[2]
guard let app = NSWorkspace.shared.runningApplications.first(where: {
    ($0.localizedName ?? "").localizedCaseInsensitiveContains(appName)
}) else {
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

var rows: [(element: AXUIElement, role: String, text: String, x: Double, y: Double, w: Double, h: Double)] = []
collect(frontWindow, &rows)

guard let target = rows.first(where: { $0.text.contains(rowText) && $0.y > 300 }) else {
    FileHandle.standardError.write("没有找到行文本：\(rowText)\n".data(using: .utf8)!)
    exit(1)
}

let candidates = rows.filter {
    $0.role.contains("CheckBox") || $0.role.contains("复选框") || $0.role == "AXCheckBox"
}.filter {
    abs($0.y - target.y) <= 24 && $0.x < target.x
}

guard let checkbox = candidates.sorted(by: { abs($0.y - target.y) < abs($1.y - target.y) }).first else {
    FileHandle.standardError.write("没有找到对应复选框：\(rowText)\n".data(using: .utf8)!)
    exit(1)
}

if AXUIElementPerformAction(checkbox.element, kAXPressAction as CFString) == .success {
    print("clicked \(rowText)")
    exit(0)
}

FileHandle.standardError.write("复选框无法按下：\(rowText)\n".data(using: .utf8)!)
exit(1)

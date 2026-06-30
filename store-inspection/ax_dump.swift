import ApplicationServices
import AppKit
import Foundation

func usage() -> Never {
    FileHandle.standardError.write("用法：ax_dump.swift <AppName> [maxDepth]\n".data(using: .utf8)!)
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

func sizeValue(_ value: CFTypeRef?) -> CGSize? {
    guard let value, CFGetTypeID(value) == AXValueGetTypeID() else { return nil }
    var size = CGSize.zero
    return AXValueGetValue(value as! AXValue, .cgSize, &size) ? size : nil
}

func children(_ element: AXUIElement) -> [AXUIElement] {
    guard let value = attr(element, kAXChildrenAttribute as String) else { return [] }
    return (value as? [AXUIElement]) ?? []
}

func dump(_ element: AXUIElement, depth: Int, maxDepth: Int, rows: inout [[String: Any]]) {
    let role = stringValue(attr(element, kAXRoleAttribute as String))
    let title = stringValue(attr(element, kAXTitleAttribute as String))
    let value = stringValue(attr(element, kAXValueAttribute as String))
    let description = stringValue(attr(element, kAXDescriptionAttribute as String))
    let help = stringValue(attr(element, kAXHelpAttribute as String))
    if !role.isEmpty || !title.isEmpty || !value.isEmpty || !description.isEmpty || !help.isEmpty {
        var row: [String: Any] = [
            "depth": depth,
            "role": role,
            "title": title,
            "value": value,
            "description": description,
            "help": help,
        ]
        if let position = pointValue(attr(element, kAXPositionAttribute as String)) {
            row["x"] = position.x
            row["y"] = position.y
        }
        if let size = sizeValue(attr(element, kAXSizeAttribute as String)) {
            row["width"] = size.width
            row["height"] = size.height
        }
        rows.append(row)
    }
    if depth >= maxDepth { return }
    for child in children(element) {
        dump(child, depth: depth + 1, maxDepth: maxDepth, rows: &rows)
    }
}

let args = CommandLine.arguments
if args.count < 2 {
    usage()
}

let appName = args[1]
let maxDepth = args.count >= 3 ? (Int(args[2]) ?? 14) : 14
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

var rows: [[String: Any]] = []
dump(frontWindow, depth: 0, maxDepth: maxDepth, rows: &rows)
let data = try JSONSerialization.data(withJSONObject: rows, options: [.prettyPrinted, .sortedKeys])
FileHandle.standardOutput.write(data)
FileHandle.standardOutput.write("\n".data(using: .utf8)!)

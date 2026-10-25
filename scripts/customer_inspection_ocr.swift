import Foundation
import Vision
import ImageIO

guard CommandLine.arguments.count == 2,
      let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: CommandLine.arguments[1]) as CFURL, nil),
      let picture = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
    fputs("Cannot read screenshot\n", stderr)
    exit(2)
}
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = false
try VNImageRequestHandler(cgImage: picture).perform([request])
let rows: [[String: Any]] = (request.results ?? []).compactMap { item in
    guard let candidate = item.topCandidates(1).first else { return nil }
    let rect = item.boundingBox
    return ["text": candidate.string, "x": rect.midX * Double(picture.width),
            "y": (1 - rect.midY) * Double(picture.height)]
}
let output = try JSONSerialization.data(withJSONObject: rows, options: [.sortedKeys])
FileHandle.standardOutput.write(output)

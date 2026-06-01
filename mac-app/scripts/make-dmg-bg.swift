#!/usr/bin/env swift
// Renders the DMG background PNG (and @2x retina variant).
// Usage:  cd mac-app && swift scripts/make-dmg-bg.swift
import AppKit
import Foundation

func render(width: Int, height: Int) -> Data {
    let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: width,
        pixelsHigh: height,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: NSColorSpaceName.calibratedRGB,
        bytesPerRow: 0,
        bitsPerPixel: 32
    )!

    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)

    let w = CGFloat(width)
    let h = CGFloat(height)

    // 1. Soft vertical gradient background
    let top    = NSColor(srgbRed: 250/255, green: 250/255, blue: 250/255, alpha: 1)
    let bottom = NSColor(srgbRed: 240/255, green: 240/255, blue: 243/255, alpha: 1)
    let grad = NSGradient(starting: top, ending: bottom)!
    grad.draw(in: NSRect(x: 0, y: 0, width: w, height: h), angle: -90)

    // Coords from create-dmg use a top-origin layout; Cocoa is bottom-origin.
    // create-dmg places icons by (x, y) with y measured from the top of the window.
    // The icon positions we configured are (150, 160) and (450, 160).
    // Convert to bottom-origin once: iconY = h - 160. Note create-dmg's "y from top"
    // refers to the icon center.
    let iconCenterY = h - (160.0 * (h / 320.0))   // proportional scale for @2x

    // 2. Title at top
    let title = "Drag AppBand to Applications"
    let titleAttrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: 14 * (h / 320.0), weight: .medium),
        .foregroundColor: NSColor(srgbRed: 58/255, green: 58/255, blue: 58/255, alpha: 1.0)
    ]
    let titleSize = (title as NSString).size(withAttributes: titleAttrs)
    (title as NSString).draw(
        at: NSPoint(x: (w - titleSize.width) / 2, y: h - (52.0 * (h / 320.0))),
        withAttributes: titleAttrs
    )

    // 3. Arrow — soft, in the middle between the two icons
    let arrowColor = NSColor(srgbRed: 110/255, green: 110/255, blue: 115/255, alpha: 1.0)
    arrowColor.setStroke()
    arrowColor.setFill()

    let arrowLeftX:  CGFloat = w * 0.40
    let arrowRightX: CGFloat = w * 0.60
    let arrowY = iconCenterY
    let thickness: CGFloat = 4 * (h / 320.0)

    let arrowPath = NSBezierPath()
    arrowPath.lineWidth = thickness
    arrowPath.lineCapStyle = .round
    arrowPath.move(to: NSPoint(x: arrowLeftX, y: arrowY))
    arrowPath.line(to: NSPoint(x: arrowRightX, y: arrowY))
    arrowPath.stroke()

    // Arrow head — two lines
    let headSize: CGFloat = 12 * (h / 320.0)
    let head = NSBezierPath()
    head.lineWidth = thickness
    head.lineCapStyle = .round
    head.lineJoinStyle = .round
    head.move(to: NSPoint(x: arrowRightX - headSize, y: arrowY + headSize * 0.7))
    head.line(to: NSPoint(x: arrowRightX, y: arrowY))
    head.line(to: NSPoint(x: arrowRightX - headSize, y: arrowY - headSize * 0.7))
    head.stroke()

    // 4. Bottom hint — Gatekeeper xattr command on two lines
    let hintLine1 = "First launch only — open Terminal and run:"
    let hintLine2 = "xattr -dr com.apple.quarantine /Applications/AppBand.app"

    let hintAttrs1: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: 10 * (h / 320.0)),
        .foregroundColor: NSColor(srgbRed: 136/255, green: 136/255, blue: 136/255, alpha: 1.0)
    ]
    let hintAttrs2: [NSAttributedString.Key: Any] = [
        .font: NSFont.monospacedSystemFont(ofSize: 10 * (h / 320.0), weight: .regular),
        .foregroundColor: NSColor(srgbRed: 90/255, green: 90/255, blue: 95/255, alpha: 1.0)
    ]
    let s1 = (hintLine1 as NSString).size(withAttributes: hintAttrs1)
    let s2 = (hintLine2 as NSString).size(withAttributes: hintAttrs2)
    (hintLine1 as NSString).draw(
        at: NSPoint(x: (w - s1.width) / 2, y: 32 * (h / 320.0)),
        withAttributes: hintAttrs1
    )
    (hintLine2 as NSString).draw(
        at: NSPoint(x: (w - s2.width) / 2, y: 16 * (h / 320.0)),
        withAttributes: hintAttrs2
    )

    NSGraphicsContext.restoreGraphicsState()

    guard let data = rep.representation(using: NSBitmapImageRep.FileType.png, properties: [:]) else {
        FileHandle.standardError.write(Data("Failed to encode PNG\n".utf8))
        exit(1)
    }
    return data
}

let here = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
let out = here.appendingPathComponent("dmg-assets")
try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)

let pngs: [(String, Int, Int)] = [
    ("background.png",    600, 320),
    ("background@2x.png", 1200, 640),
]
for (name, w, h) in pngs {
    let data = render(width: w, height: h)
    try data.write(to: out.appendingPathComponent(name))
    print("Wrote \(name) (\(w)x\(h))")
}

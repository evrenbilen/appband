#!/usr/bin/env swift
// Renders AppBand.iconset/ from scratch, then assembles AppBand.icns via iconutil.
// Usage:  cd mac-app && swift scripts/make-icon.swift
import AppKit
import Foundation

func render(size: CGFloat) -> Data {
    let intSize = Int(size)
    // Use NSBitmapImageRep directly — works without a window server / display context.
    let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: intSize,
        pixelsHigh: intSize,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    )!
    rep.size = NSSize(width: size, height: size)

    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    defer { NSGraphicsContext.restoreGraphicsState() }

    let s = size

    // Rounded-square background — corner radius ~size * 0.225 per Apple convention.
    let r = s * 0.225
    let rect = NSRect(x: 0, y: 0, width: s, height: s)
    let bg = NSBezierPath(roundedRect: rect, xRadius: r, yRadius: r)

    // Blue gradient (top -> bottom), tuned to macOS system blue.
    let top    = NSColor(srgbRed: 64/255,  green: 156/255, blue: 255/255, alpha: 1)
    let bottom = NSColor(srgbRed: 0/255,   green: 113/255, blue: 227/255, alpha: 1)
    let grad = NSGradient(starting: top, ending: bottom)!
    grad.draw(in: bg, angle: -90)

    // White bars (horizontal, decreasing width) — mimics a bandwidth chart.
    let leftPad = s * 0.16
    let barH    = s * 0.080
    let barR    = barH * 0.4
    let gap     = s * 0.040

    // Vertical placement: center the stack of 5 bars + 4 gaps.
    let stackH      = 5 * barH + 4 * gap
    let stackBottom = (s - stackH) / 2

    // Widths from longest (top, visually) to shortest (bottom), as fractions of s.
    let widths: [CGFloat] = [0.68, 0.56, 0.44, 0.34, 0.24]

    NSColor.white.withAlphaComponent(0.95).setFill()
    for (i, w) in widths.enumerated() {
        // i=0 is longest bar, drawn at the top visually (highest y in AppKit coords)
        let y = stackBottom + CGFloat(4 - i) * (barH + gap)
        let barRect = NSRect(x: leftPad, y: y, width: s * w, height: barH)
        let bar = NSBezierPath(roundedRect: barRect, xRadius: barR, yRadius: barR)
        bar.fill()
    }

    // Subtle inner highlight along the top half — slight gloss.
    let highlightRect = NSRect(x: 0, y: s * 0.5, width: s, height: s * 0.5)
    let highlight = NSBezierPath(roundedRect: highlightRect, xRadius: r, yRadius: r)
    let glow = NSGradient(
        starting: NSColor.white.withAlphaComponent(0.10),
        ending:   NSColor.white.withAlphaComponent(0.0)
    )!
    glow.draw(in: highlight, angle: -90)

    guard let data = rep.representation(using: .png, properties: [:]) else {
        FileHandle.standardError.write(Data("Failed to encode PNG at \(size)\n".utf8))
        exit(1)
    }
    return data
}

// Standard macOS iconset sizes
struct IconSize {
    let base: Int
    let scale: Int
    var px: CGFloat { CGFloat(base * scale) }
    var filename: String {
        scale == 1 ? "icon_\(base)x\(base).png" : "icon_\(base)x\(base)@2x.png"
    }
}

let sizes: [IconSize] = [
    .init(base: 16,  scale: 1), .init(base: 16,  scale: 2),
    .init(base: 32,  scale: 1), .init(base: 32,  scale: 2),
    .init(base: 128, scale: 1), .init(base: 128, scale: 2),
    .init(base: 256, scale: 1), .init(base: 256, scale: 2),
    .init(base: 512, scale: 1), .init(base: 512, scale: 2),
]

let here    = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
let iconset = here.appendingPathComponent("AppBand.iconset")
try? FileManager.default.removeItem(at: iconset)
try! FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)

for sz in sizes {
    let data = render(size: sz.px)
    let url  = iconset.appendingPathComponent(sz.filename)
    try! data.write(to: url)
    print("Wrote \(sz.filename) at \(Int(sz.px))x\(Int(sz.px))")
}
print("Icon set written to \(iconset.path)")

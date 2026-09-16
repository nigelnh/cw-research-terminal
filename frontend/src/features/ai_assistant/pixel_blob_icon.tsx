interface PixelBlobIconProps {
  size?: number;
}

/**
 * Static happy Blob from the user-provided pixel icon kit.
 *
 * Movement belongs to the launcher's explicit drag gesture. Keeping the SVG free of
 * animation and transforms prevents the character from wandering, bobbing, or
 * shifting independently of that launcher position.
 */
export function PixelBlobIcon({ size = 32 }: PixelBlobIconProps) {
  return (
    <svg
      aria-hidden="true"
      data-ai-blob="true"
      viewBox="0 0 32 26"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      shapeRendering="crispEdges"
      style={{
        width: size,
        height: Math.round((size * 26) / 32),
        display: "block",
        flex: "none",
        pointerEvents: "none",
        animation: "none",
        transform: "none",
      }}
    >
      <path d="M10 2H22V4H26V7H29V11H31V19H29V22H27V24H5V22H3V19H1V11H3V7H6V4H10V2Z" fill="#122c44" />
      <path d="M10 4H22V6H25V8H27V11H29V19H27V21H25V23H7V21H5V19H3V11H5V8H7V6H10V4Z" fill="#58b3ea" />
      <path d="M7 21H25V23H7V21ZM5 19H7V21H5V19ZM25 19H27V21H25V19Z" fill="#296ea6" />
      <path d="M10 5H17V7H10V5ZM7 8H10V11H7V8ZM6 11H8V14H6V11Z" fill="#b9e7fc" />
      <rect x="18" y="5" width="3" height="1" fill="#eaf6fd" />
      <rect x="6" y="16" width="3" height="2" fill="#ff8da1" />
      <rect x="23" y="16" width="3" height="2" fill="#ff8da1" />
      <rect x="10" y="12" width="2" height="3" fill="#122c44" />
      <rect x="10" y="12" width="1" height="1" fill="#ffffff" />
      <rect x="20" y="12" width="2" height="3" fill="#122c44" />
      <rect x="20" y="12" width="1" height="1" fill="#ffffff" />
      <rect x="15" y="16" width="2" height="1" fill="#122c44" />
      <rect x="14" y="15" width="1" height="1" fill="#122c44" />
      <rect x="17" y="15" width="1" height="1" fill="#122c44" />
    </svg>
  );
}

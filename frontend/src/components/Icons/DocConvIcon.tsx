import { forwardRef, memo } from "react";

export interface DocConvIconProps {
  size?: number | string;
  color?: string;
  className?: string;
  style?: React.CSSProperties;
  strokeWidth?: number; // ignored — kept for LucideIcon compat
  "aria-label"?: string;
}

/**
 * Renders a DocConv icon from pre-computed SVG path data.
 * viewBox is 2560×2560 (potrace coordinate space).
 * Paths are Y-flipped via transform group.
 */
const DocConvIconInner = forwardRef<SVGSVGElement, DocConvIconProps & { paths: string[] }>(
  ({ paths, size = 24, color, className, style, "aria-label": ariaLabel }, ref) => (
    <svg
      ref={ref}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 2560 2560"
      width={size}
      height={size}
      fill={color ?? "currentColor"}
      className={className}
      style={style}
      aria-label={ariaLabel}
      role={ariaLabel ? "img" : undefined}
    >
      <g transform="translate(0,2560) scale(1,-1)">
        {paths.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>
    </svg>
  ),
);
DocConvIconInner.displayName = "DocConvIcon";

/**
 * Factory: creates a named icon component from path data.
 * The returned component matches the LucideIcon interface.
 */
export function createDocConvIcon(name: string, paths: string[]) {
  const Icon = memo(
    forwardRef<SVGSVGElement, DocConvIconProps>((props, ref) => (
      <DocConvIconInner ref={ref} paths={paths} {...props} />
    )),
  );
  Icon.displayName = name;
  return Icon;
}

export type DocConvIconComponent = ReturnType<typeof createDocConvIcon>;

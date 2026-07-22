interface CorgiLogoProps {
  size?: number;
  className?: string;
}

export default function CorgiLogo({ size = 28, className }: CorgiLogoProps) {
  return (
    <img
      alt="Document Conversion"
      className={className}
      draggable={false}
      height={size}
      src="/corgi-logo.png"
      width={size}
    />
  );
}

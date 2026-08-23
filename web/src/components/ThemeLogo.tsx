import darkLogoUrl from "../assets/elsewise-logo-dark.svg";
import lightLogoUrl from "../assets/elsewise-logo-light.svg";

export function ThemeLogo({ className = "" }: { className?: string }) {
  return (
    <span className={`theme-logo ${className}`.trim()} aria-hidden="true">
      <img className="theme-logo-dark" src={darkLogoUrl} alt="" />
      <img className="theme-logo-light" src={lightLogoUrl} alt="" />
    </span>
  );
}

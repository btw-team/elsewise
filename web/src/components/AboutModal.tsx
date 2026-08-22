import { GithubLogo } from "@phosphor-icons/react/GithubLogo";
import { HardDrive } from "@phosphor-icons/react/HardDrive";
import { TerminalWindow } from "@phosphor-icons/react/TerminalWindow";
import { X } from "@phosphor-icons/react/X";

import elsewiseLogoUrl from "../assets/elsewise-logo.png";
import kofiIconUrl from "../assets/kofi-icon.png";
import maintainerAvatarUrl from "../assets/white-bunny-avatar.png";
import { EXTERNAL_LINKS } from "../externalLinks";
import type { TranslationKey } from "../i18n/catalogs";
import { ModalPortal } from "./ModalPortal";
import { useModalFocus } from "./useModalFocus";

const CORE_STACK = [
  "Python",
  "FastAPI",
  "React",
  "TypeScript",
  "SQLite",
  "WebExtensions",
] as const;

const THIRD_PARTY = [
  "FastAPI",
  "SQLAlchemy",
  "Alembic",
  "Pydantic",
  "Uvicorn",
  "React",
  "Vite",
  "Phosphor Icons",
  "React Markdown",
] as const;

export function AboutModal({
  t,
  onClose,
}: {
  t: (key: TranslationKey) => string;
  onClose: () => void;
}) {
  const dialog = useModalFocus(onClose);

  return (
    <ModalPortal>
      <div
        className="dialog-backdrop"
        role="presentation"
        onMouseDown={onClose}
      >
        <section
          ref={dialog}
          tabIndex={-1}
          className="dialog about-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="about-dialog-title"
          onMouseDown={(event) => event.stopPropagation()}
        >
          <header className="dialog-heading about-heading">
            <h2 id="about-dialog-title">{t("aboutTitle")}</h2>
            <button
              type="button"
              className="about-close"
              aria-label={t("close")}
              title={t("close")}
              onClick={onClose}
            >
              <X aria-hidden="true" weight="regular" />
            </button>
          </header>

          <div className="about-hero">
            <img className="about-logo" src={elsewiseLogoUrl} alt="" />
            <div>
              <div className="about-product-line">
                <h3>Elsewise</h3>
                <span className="about-version">v{__APP_VERSION__}</span>
              </div>
              <p className="about-description">{t("aboutDescription")}</p>
              <p className="about-hero-note">
                <HardDrive aria-hidden="true" weight="regular" />
                <span>{t("aboutLocalFirst")}</span>
              </p>
              <p className="about-hero-note">
                <TerminalWindow aria-hidden="true" weight="regular" />
                <span>{t("aboutAgentCliRequirement")}</span>
              </p>
            </div>
          </div>

          <div className="about-facts">
            <section className="about-fact-card">
              <span>{t("aboutProject")}</span>
              <a
                className="about-project-link"
                href={EXTERNAL_LINKS.project}
                target="_blank"
                rel="noopener noreferrer"
              >
                <GithubLogo aria-hidden="true" weight="fill" />
                btw-team/elsewise
              </a>
            </section>
            <section className="about-fact-card">
              <span>{t("aboutLicense")}</span>
              <a
                className="about-license-link"
                href={EXTERNAL_LINKS.license}
                target="_blank"
                rel="noopener noreferrer"
              >
                {t("aboutLicenseName")}
              </a>
              <p>{t("aboutLicenseNotice")}</p>
            </section>
          </div>

          <section className="about-section">
            <h3>{t("aboutCoreStack")}</h3>
            <div className="about-stack" aria-label={t("aboutCoreStack")}>
              {CORE_STACK.map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>
          </section>

          <section className="about-section about-third-party">
            <h3>{t("aboutThirdParty")}</h3>
            <p className="about-package-list">{THIRD_PARTY.join(" · ")}</p>
            <p>{t("aboutThirdPartyNotice")}</p>
          </section>

          <footer className="about-footer">
            <p className="about-maintainer">
              <img src={maintainerAvatarUrl} alt="" />
              <span>
                {t("aboutMaintainedBy")} <strong>BTW Team</strong>
              </span>
            </p>
            <a
              className="about-support-link"
              href={EXTERNAL_LINKS.support}
              target="_blank"
              rel="noopener noreferrer"
            >
              <img src={kofiIconUrl} alt="" />
              <span>{t("aboutSupport")}</span>
            </a>
          </footer>
        </section>
      </div>
    </ModalPortal>
  );
}

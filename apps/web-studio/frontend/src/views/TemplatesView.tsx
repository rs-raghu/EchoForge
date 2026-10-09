import { useEffect, useState } from "react";
import { fetchProjectDesign, fetchTemplates, saveProjectDesign } from "../api";
import type { DesignSettings, ProjectDesign, TemplateOption } from "../types";
import { EmptyPanel, type StudioPageProps } from "./ViewSharedComponents";

const aspectRatios = ["16:9", "9:16", "1:1"];
const resolutions = ["720p", "1080p", "1440p"];
const fpsOptions = [24, 30, 60];
const animations = ["none", "fade"];
const positions = ["center", "bottom", "top"];

export function TemplatesView({ project, onProjectChanged, setError }: StudioPageProps) {
  const [templates, setTemplates] = useState<TemplateOption[]>([]);
  const [design, setDesign] = useState<ProjectDesign | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const templatePayload = await fetchTemplates();
        const designPayload = project ? await fetchProjectDesign(project.id) : null;
        if (!cancelled) {
          setTemplates(templatePayload);
          setDesign(designPayload);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Templates could not be loaded");
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [project?.id, setError]);

  function chooseTemplate(template: TemplateOption) {
    if (!project) {
      return;
    }
    setDesign({
      projectId: project.id,
      templateId: template.id,
      templateName: template.name,
      settings: template.settings,
      isSaved: false,
      designPath: "",
      renderPropsPath: "",
    });
    setStatus("Template selected");
  }

  function updateSetting<K extends keyof DesignSettings>(key: K, value: DesignSettings[K]) {
    if (!design) {
      return;
    }
    setDesign({ ...design, settings: { ...design.settings, [key]: value }, isSaved: false });
    setStatus(null);
  }

  async function saveDesign() {
    if (!project || !design) {
      return;
    }
    setBusy("save-design");
    setError(null);
    try {
      const next = await saveProjectDesign(project.id, design);
      setDesign(next);
      setStatus("Design saved");
      await onProjectChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Design could not be saved");
    } finally {
      setBusy(null);
    }
  }

  if (!project) {
    return <EmptyPanel title="Select a project" />;
  }

  return (
    <section className="studio-workbench">
      <section className="panel">
        <div className="panel-header">
          <h2>Templates</h2>
        </div>
        <div className="template-grid">
          {templates.map((template) => (
            <article className={design?.templateId === template.id ? "template-card selected" : "template-card"} key={template.id}>
              <div className="template-preview" style={{ backgroundColor: template.settings.backgroundColor }}>
                <span style={{ color: template.settings.textColor }}>Aa</span>
              </div>
              <strong>{template.name}</strong>
              <span>{template.aspectRatio}</span>
              <small>{template.description}</small>
              <button className="button small" onClick={() => chooseTemplate(template)} type="button">
                Use Template
              </button>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Design</h2>
          <button className="button primary" disabled={!design || busy === "save-design"} onClick={() => void saveDesign()} type="button">
            Save Design
          </button>
        </div>
        {design ? (
          <div className="settings-grid">
            <label>
              Aspect Ratio
              <select value={design.settings.aspectRatio} onChange={(event) => updateSetting("aspectRatio", event.target.value)}>
                {aspectRatios.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Resolution
              <select value={design.settings.resolution} onChange={(event) => updateSetting("resolution", event.target.value)}>
                {resolutions.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label>
              FPS
              <select value={design.settings.fps} onChange={(event) => updateSetting("fps", Number(event.target.value))}>
                {fpsOptions.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Font
              <input value={design.settings.fontFamily} onChange={(event) => updateSetting("fontFamily", event.target.value)} />
            </label>
            <label>
              Font Size
              <input
                min="24"
                step="1"
                type="number"
                value={design.settings.fontSize}
                onChange={(event) => updateSetting("fontSize", Number(event.target.value))}
              />
            </label>
            <label>
              Position
              <select value={design.settings.textPosition} onChange={(event) => updateSetting("textPosition", event.target.value)}>
                {positions.map((value) => (
                  <option key={value} value={value}>
                    {value.replace("_", " ")}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Text Color
              <input type="color" value={design.settings.textColor} onChange={(event) => updateSetting("textColor", event.target.value)} />
            </label>
            <label>
              Highlight
              <input
                type="color"
                value={design.settings.highlightColor}
                onChange={(event) => updateSetting("highlightColor", event.target.value)}
              />
            </label>
            <label>
              Background
              <input
                type="color"
                value={design.settings.backgroundColor}
                onChange={(event) => updateSetting("backgroundColor", event.target.value)}
              />
            </label>
            <label>
              Animation
              <select value={design.settings.animation} onChange={(event) => updateSetting("animation", event.target.value)}>
                {animations.map((value) => (
                  <option key={value} value={value}>
                    {value.replace("_", " ")}
                  </option>
                ))}
              </select>
            </label>
            <label className="toggle-row">
              <input
                checked={design.settings.watermark}
                onChange={(event) => updateSetting("watermark", event.target.checked)}
                type="checkbox"
              />
              Watermark
            </label>
          </div>
        ) : (
          <div className="empty-state">
            <strong>No design loaded</strong>
          </div>
        )}
        <div className="save-state">{busy ? "Saving..." : status ?? (design?.isSaved ? "Saved" : "Unsaved changes")}</div>
      </section>
    </section>
  );
}

import { useEffect, useState } from "react";
import { fetchSettings, saveSettings } from "../api";
import type { AppSettings } from "../types";
import { EmptyPanel } from "./ViewSharedComponents";

export function SettingsView({ setError }: { setError: (message: string | null) => void }) {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const payload = await fetchSettings();
        if (!cancelled) {
          setSettings(payload);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Settings could not be loaded");
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [setError]);

  async function save() {
    if (!settings) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setSettings(await saveSettings(settings));
      setStatus("Settings saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Settings could not be saved");
    } finally {
      setBusy(false);
    }
  }

  if (!settings) {
    return <EmptyPanel title="Loading settings" />;
  }

  return (
    <section className="studio-workbench compact">
      <section className="panel">
        <div className="panel-header">
          <h2>Settings</h2>
          <button className="button primary" disabled={busy} onClick={() => void save()} type="button">
            Save
          </button>
        </div>
        <div className="settings-grid">
          <label>
            Default Country
            <select value={settings.defaultCountry} onChange={(event) => setSettings({ ...settings, defaultCountry: event.target.value })}>
              <option value="US">United States</option>
              <option value="IN">India</option>
              <option value="GLOBAL">Global</option>
              <option value="GB">United Kingdom</option>
            </select>
          </label>
          <label>
            Default Privacy
            <select
              value={settings.defaultPrivacy}
              onChange={(event) => setSettings({ ...settings, defaultPrivacy: event.target.value as AppSettings["defaultPrivacy"] })}
            >
              <option value="private">private</option>
              <option value="unlisted">unlisted</option>
              <option value="public">public</option>
            </select>
          </label>
          <label>
            Preview Resolution
            <select value={settings.previewResolution} onChange={(event) => setSettings({ ...settings, previewResolution: event.target.value })}>
              <option value="480p">480p</option>
              <option value="720p">720p</option>
              <option value="1080p">1080p</option>
            </select>
          </label>
          <label>
            Render Quality
            <select value={settings.renderQuality} onChange={(event) => setSettings({ ...settings, renderQuality: event.target.value })}>
              <option value="draft">draft</option>
              <option value="standard">standard</option>
              <option value="high">high</option>
            </select>
          </label>
          <label>
            Autosave Seconds
            <input
              min="1"
              type="number"
              value={settings.autosaveSeconds}
              onChange={(event) => setSettings({ ...settings, autosaveSeconds: Number(event.target.value) })}
            />
          </label>
        </div>
        <div className="runtime-list">
          <div>
            <span>Workspace</span>
            <code>{settings.workspaceRoot}</code>
          </div>
          <div>
            <span>Database</span>
            <code>{settings.databasePath}</code>
          </div>
          <div>
            <span>Renderer</span>
            <code>{settings.remotionPath}</code>
          </div>
        </div>
        {status ? <div className="success-note">{status}</div> : null}
      </section>
    </section>
  );
}

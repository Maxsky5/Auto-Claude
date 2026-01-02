import { Label } from '../ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { AVAILABLE_MODELS_BY_BACKEND } from '../../../shared/constants';
import type { ProjectSettings } from '../../../shared/types';
import { useSettingsStore } from '../../stores/settings-store';

interface AgentConfigSectionProps {
  settings: ProjectSettings;
  onUpdateSettings: (updates: Partial<ProjectSettings>) => void;
}

export function AgentConfigSection({ settings, onUpdateSettings }: AgentConfigSectionProps) {
  const appSettings = useSettingsStore((state) => state.settings);
  const backend = appSettings.agentRuntime || 'claude-code';
  const availableModels = AVAILABLE_MODELS_BY_BACKEND[backend] || AVAILABLE_MODELS_BY_BACKEND['claude-code'];

  return (
    <section className="space-y-4">
      <h3 className="text-sm font-semibold text-foreground">Agent Configuration</h3>
      <div className="space-y-2">
        <Label htmlFor="model" className="text-sm font-medium text-foreground">Model</Label>
        <Select
          value={settings.model}
          onValueChange={(value) => onUpdateSettings({ model: value })}
        >
          <SelectTrigger id="model">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {availableModels.map((model) => (
              <SelectItem key={model.value} value={model.value}>
                {model.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </section>
  );
}

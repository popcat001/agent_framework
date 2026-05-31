import { HelpCircle } from "lucide-react";
import { resolveIcon } from "../config/iconRegistry";
import { useAuth } from "../contexts/AuthContext";
import { project } from "../config/project";
import type { AgentInfo } from "../types";

interface WelcomeScreenProps {
  onSelectQuestion: (question: string) => void;
  /** Active agent — when its `sample_questions` list is non-empty it is
   *  rendered instead of the project-level default. */
  agent?: AgentInfo | null;
}

export function WelcomeScreen({ onSelectQuestion, agent }: WelcomeScreenProps) {
  const { user } = useAuth();
  const firstName = user?.display_name?.split(" ")[0] || "there";
  const questions =
    agent?.sample_questions && agent.sample_questions.length > 0
      ? agent.sample_questions
      : project.sampleQuestions;

  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6 pb-4">
      {/* Welcome header */}
      <div className="text-center mb-10">
        <img src={project.appLogo} alt={project.name} className="w-64 mx-auto mb-6" />
        <p className="text-lg" style={{ color: "var(--text-secondary)" }}>
          Hi {firstName}, how can I help you today?
        </p>
      </div>

      {/* Sample questions grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-2xl w-full">
        {questions.map((q) => {
          const Icon = resolveIcon(q.icon) ?? HelpCircle;
          return (
            <button
              key={q.text}
              onClick={() => onSelectQuestion(q.text)}
              className="flex items-start gap-3 px-4 py-3.5 rounded-xl text-left text-sm transition-all cursor-pointer group"
              style={{
                background: "var(--bg-input)",
                border: "1px solid var(--border)",
                color: "var(--text-primary)",
              }}
              onMouseOver={(e) => {
                e.currentTarget.style.borderColor = "var(--accent)";
                e.currentTarget.style.boxShadow = "0 2px 8px rgba(224, 122, 58, 0.1)";
              }}
              onMouseOut={(e) => {
                e.currentTarget.style.borderColor = "var(--border)";
                e.currentTarget.style.boxShadow = "none";
              }}
            >
              <Icon
                size={18}
                className="mt-0.5 shrink-0 transition-colors"
                style={{ color: "var(--text-secondary)" }}
              />
              <span>{q.text}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

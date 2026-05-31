export interface ProjectTheme {
  bgPrimary: string;
  bgSidebar: string;
  bgInput: string;
  textPrimary: string;
  textSecondary: string;
  accent: string;
  accentHover: string;
  border: string;
}

export interface SampleQuestion {
  icon: string;
  text: string;
}

export interface ProjectConfig {
  name: string;
  tagline: string;
  orgLogo: string;
  appLogo: string;
  pageTitle: string;
  favicon: string;
  serviceName: string;
  disclaimer: string;
  theme: ProjectTheme;
  sampleQuestions: SampleQuestion[];
}

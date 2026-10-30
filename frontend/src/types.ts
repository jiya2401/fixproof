import type { ProjectInfo } from './api'

export type Source =
  | { kind: 'example'; name: string; issue: string }
  | { kind: 'project'; info: ProjectInfo; initialTestId?: string }

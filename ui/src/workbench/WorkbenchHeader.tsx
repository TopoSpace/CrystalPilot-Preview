import { createContext, useContext, type ReactNode } from "react";

export const ChromeControls = createContext<{ left?: ReactNode; right?: ReactNode }>({});

/** Controls own layout space, so collapsing either pane cannot cover a title. */
export function WorkbenchHeader({ children }: { children?: ReactNode }) {
  const { left, right } = useContext(ChromeControls);
  return <header className="workbench-header" data-testid="workbench-header">
    {left}
    <div className="workbench-header-content">{children}</div>
    {right}
  </header>;
}

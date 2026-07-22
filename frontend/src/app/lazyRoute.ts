import { Suspense, createElement, type ComponentType, type LazyExoticComponent } from "react";

export function renderLazyRoute(Component: LazyExoticComponent<ComponentType>) {
  return createElement(
    Suspense,
    {
      fallback: createElement(
        "section",
        {
          "aria-live": "polite",
          className: "route-loading-fallback",
          "data-testid": "route-loading-fallback",
          style: { minHeight: 240, display: "grid", placeItems: "center" }
        },
        createElement("span", null, "Loading page...")
      )
    },
    createElement(Component)
  );
}

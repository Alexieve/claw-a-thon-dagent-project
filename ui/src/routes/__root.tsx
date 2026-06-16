import { createRootRoute, Outlet } from "@tanstack/react-router";
import { TanStackRouterDevtools } from "@tanstack/router-devtools";
import { NotFoundPage } from "@/shared/components/not-found-page";
import { AppCfg } from "@/shared/config/app";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";

export const Route = createRootRoute({
  component: () => (
    <>
      <Outlet />
      {!AppCfg.isProd && (
        <>
          <TanStackRouterDevtools position="bottom-right" />
          <ReactQueryDevtools initialIsOpen={false} />
        </>
      )}
    </>
  ),
  notFoundComponent: () => <NotFoundPage />,
});

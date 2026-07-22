export function getDatabaseBasePath(pathname: string): string {
  return pathname.startsWith("/database") ? "/database" : "/projects";
}

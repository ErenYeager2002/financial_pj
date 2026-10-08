"use client";
import {useEffect, useState} from 'react';
import {fileDownloadUrl, fileRequest} from './pi-file-transfer';
import {scanPiArtifacts, type PiDirectoryPage} from './pi-artifact-scan';

export type PiArtifactsView = {
  files: {path: string; size: number; href: string}[];
  truncated: boolean;
  error: string;
};
const empty: PiArtifactsView = {files: [], truncated: false, error: ''};
export function usePiArtifacts(sessionId: string, enabled: boolean, revision: string) {
  const [state, setState] = useState({sessionId, view: empty});
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    void scanPiArtifacts((query, signal) => fileRequest<PiDirectoryPage>(sessionId,
      {action: 'list', source: 'workspace', ...query}, signal), controller.signal)
      .then(result => {
        if (!controller.signal.aborted) setState({sessionId, view: {
          files: result.files.map(file => ({...file, href: fileDownloadUrl(sessionId, 'workspace', file.path)})),
          truncated: result.truncated, error: ''
        }});
      }).catch(cause => {
        if (!controller.signal.aborted) setState(current => ({sessionId, view: {...(current.sessionId === sessionId ? current.view : empty),
          error: cause instanceof Error ? cause.message : '下载文件读取失败'}}));
      });
    return () => controller.abort();
  }, [sessionId, enabled, revision, refresh]);
  return {view: state.sessionId === sessionId ? state.view : empty, refresh: () => setRefresh(value => value + 1)};
}

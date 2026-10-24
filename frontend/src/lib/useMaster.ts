import { useSyncExternalStore } from 'react'
import { masterState, subscribeMaster } from '../data/master'

/** 마스터를 받는 중인지, 손에 있는지, 못 받았는지.
 *
 *  화면이 이 값을 읽어 「종목 목록을 받는 중입니다」와 목록 사이를 오갑니다 —
 *  **「없다」와 「아직 모른다」는 다른 상태**라 빈 목록으로 뭉개지 않습니다. */
export function useMasterStatus() {
  return useSyncExternalStore(subscribeMaster, masterState, masterState)
}

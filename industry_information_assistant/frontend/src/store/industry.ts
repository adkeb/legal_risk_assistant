/**
 * Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
 * 未经授权，禁止转售或仿制。
 */

/**
 * 法律风控领域状态管理。
 * 保留该文件是为了兼容少量历史调用点，但只提供法律风控单域配置。
 */
import { proxy, subscribe } from 'valtio'

export interface IndustryConfig {
  id: string
  name: string
  description: string
  newsKeywords: string[]
  biddingKeywords: string[]
  researchKeywords: string[]
}

export const INDUSTRY_CONFIGS: IndustryConfig[] = [
  {
    id: 'legal_risk',
    name: '法律风控',
    description: '合同审查、合规义务、监管风险、证据链和整改建议',
    newsKeywords: [
      '法律风险',
      '合规义务',
      '监管处罚',
      '合同条款',
    ],
    biddingKeywords: [
      '合同审查',
      '合规审查',
      '法律尽调',
    ],
    researchKeywords: ['法律风控', '合同风险', '合规义务', '证据链', '整改建议'],
  },
]

export interface IndustryState {
  currentIndustryId: string
  industries: IndustryConfig[]
}

const getStoredIndustryId = (): string => {
  if (typeof window !== 'undefined') {
    const stored = localStorage.getItem('selected_industry_id')
    return stored === 'legal_risk' ? stored : 'legal_risk'
  }
  return 'legal_risk'
}

export const industryState = proxy<IndustryState>({
  currentIndustryId: getStoredIndustryId(),
  industries: INDUSTRY_CONFIGS,
})

subscribe(industryState, () => {
  if (typeof window !== 'undefined') {
    localStorage.setItem('selected_industry_id', 'legal_risk')
  }
})

export const getCurrentIndustry = (): IndustryConfig => {
  const industry = industryState.industries.find(
    (i) => i.id === industryState.currentIndustryId
  )
  return industry || INDUSTRY_CONFIGS[0]
}

export const setCurrentIndustry = () => {
  industryState.currentIndustryId = 'legal_risk'
}

export const getIndustryOptions = () => {
  return industryState.industries.map((i) => ({
    value: i.id,
    label: i.name,
    description: i.description,
  }))
}

/**
 * Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
 * 未经授权，禁止转售或仿制。
 */

import IconBg from '@/assets/index/bg.png'
import IconSearch from '@/assets/index/search.svg'
import { ArrowRightOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { useNavigate } from 'react-router-dom'
import styles from './index.module.scss'

const scenarios = [
  {
    title: '合同条款风险',
    desc: '交付、付款、违约、免责',
  },
  {
    title: '合规义务识别',
    desc: '法条依据、监管口径、义务期限',
  },
  {
    title: '监管处罚分析',
    desc: '处罚事实、裁量因素、整改动作',
  },
  {
    title: '证据链核验',
    desc: '来源追踪、引用核查、证明强度',
  },
]

const capabilities = ['风险等级', '义务期限', '整改建议', '引用核验']

export default function Index() {
  const navigate = useNavigate()

  const startResearch = () => {
    navigate('/chat?title=法律风控研究')
  }

  return (
    <div className={styles['index-page']}>
      <div className={styles.header}>
        <img className={styles.bg} src={IconBg} />
        <div className={styles['header-copy']}>
          <div className={styles.eyebrow}>LEGAL RISK RESEARCH</div>
          <h1 className={styles.title}>法律风控 DeepResearch</h1>
          <div className={styles.desc}>
            面向合同审查、合规义务、监管风险和证据链核验的 AI 研究工作台
          </div>
          <div className={styles['capability-list']}>
            {capabilities.map((item) => (
              <span key={item}>{item}</span>
            ))}
          </div>
        </div>
      </div>

      <div className={styles['workbench-grid']}>
        <div className={styles['entry-panel']}>
          <div className={styles['entry-panel__icon']}>
            <img src={IconSearch} />
          </div>
          <div className={styles['entry-panel__content']}>
            <div className={styles['entry-panel__title']}>开始法律风控研究</div>
            <div className={styles['entry-panel__desc']}>
              生成带免责声明、风险等级、义务期限、整改建议和引用核验的法律风控报告
            </div>
          </div>
          <Button
            type="primary"
            size="large"
            onClick={startResearch}
            icon={<ArrowRightOutlined />}
          >
            新建研究
          </Button>
        </div>

        <div className={styles['status-panel']}>
          <div className={styles['status-panel__label']}>研究框架</div>
          <div className={styles['status-panel__value']}>检索 · 分析 · 报告 · 复核</div>
          <div className={styles['status-panel__line']} />
          <div className={styles['status-panel__meta']}>
            法律依据、事实材料和业务动作在同一流程中沉淀。
          </div>
        </div>
      </div>

      <div className={styles['scenario-list']}>
        {scenarios.map((scenario) => (
          <div className={styles['scenario-item']} key={scenario.title}>
            <div className={styles['scenario-title']}>{scenario.title}</div>
            <div className={styles['scenario-desc']}>{scenario.desc}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

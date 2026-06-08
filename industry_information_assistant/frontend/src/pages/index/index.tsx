/**
 * Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
 * 未经授权，禁止转售或仿制。
 */

import IconBg from '@/assets/index/bg.png'
import IconSearch from '@/assets/index/search.svg'
import { Button } from 'antd'
import { useNavigate } from 'react-router-dom'
import styles from './index.module.scss'

export default function Index() {
  const navigate = useNavigate()

  const startResearch = () => {
    navigate('/chat?title=法律风控研究')
  }

  return (
    <div className={styles['index-page']}>
      <div className={styles.header}>
        <img className={styles.bg} src={IconBg} />
        <div className={styles.title}>法律风控 DeepResearch</div>
        <div className={styles.desc}>
          面向合同审查、合规义务、监管风险和证据链核验的 AI 研究工作台
        </div>
      </div>

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
        <Button type="primary" size="large" onClick={startResearch}>
          新建研究
        </Button>
      </div>

      <div className={styles['scenario-list']}>
        <div className={styles['scenario-item']}>合同条款风险</div>
        <div className={styles['scenario-item']}>合规义务识别</div>
        <div className={styles['scenario-item']}>监管处罚分析</div>
        <div className={styles['scenario-item']}>证据链核验</div>
      </div>
    </div>
  )
}

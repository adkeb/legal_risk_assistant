/**
 * Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
 * 未经授权，禁止转售或仿制。
 */

import IconHistory from '@/assets/layout/history.svg'
import IconHome from '@/assets/layout/home.svg'
import IconKnowledge from '@/assets/layout/knowledge.svg'
import IconNewChat from '@/assets/layout/newchat.svg'
import { useMemo, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { NavItem } from './nav-item'
import { SessionDrawer } from '@/components/session-drawer'
import './nav.scss'

export function Nav() {
  const { pathname } = useLocation()
  const [sessionDrawerOpen, setSessionDrawerOpen] = useState(false)

  const items = useMemo(
    () => [
      {
        key: 'home',
        label: '法律风控',
        icon: IconHome,
        href: '/',
      },
      {
        key: 'newchat',
        label: '新建研究',
        icon: IconNewChat,
        href: '/chat',
      },
      {
        key: 'history',
        label: '研究历史',
        icon: IconHistory,
        href: '#',
        onClick: () => setSessionDrawerOpen(true),
      },
      {
        key: 'knowledge',
        label: '法律知识库',
        icon: IconKnowledge,
        href: '/knowledge',
      },
    ],
    [],
  )

  return (
    <>
      <div className="base-layout-nav">
        {items.map(({ key, onClick, ...item }) => (
          <NavItem
            key={key}
            {...item}
            active={pathname === item.href}
            onClick={onClick}
          />
        ))}
      </div>
      <SessionDrawer
        open={sessionDrawerOpen}
        onClose={() => setSessionDrawerOpen(false)}
      />
    </>
  )
}

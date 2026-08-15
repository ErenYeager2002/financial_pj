'use client';

import { useState } from 'react';
import { useSuspenseQuery } from '@tanstack/react-query';
import { pokemonOptions } from '../api/queries';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter
} from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';

const POKEMON_IDS = [25, 1, 4, 7, 6, 150, 133, 39, 143, 94];

const POKEMON_NAMES: Record<number, string> = {
  1: '妙蛙种子',
  4: '小火龙',
  6: '喷火龙',
  7: '杰尼龟',
  25: '皮卡丘',
  39: '胖丁',
  94: '耿鬼',
  133: '伊布',
  143: '卡比兽',
  150: '超梦'
};

const TYPE_NAMES: Record<string, string> = {
  bug: '虫',
  dragon: '龙',
  electric: '电',
  fairy: '妖精',
  fighting: '格斗',
  fire: '火',
  flying: '飞行',
  ghost: '幽灵',
  grass: '草',
  ground: '地面',
  ice: '冰',
  normal: '一般',
  poison: '毒',
  psychic: '超能力',
  rock: '岩石',
  steel: '钢',
  water: '水'
};

const STAT_NAMES: Record<string, string> = {
  hp: '生命值',
  attack: '攻击',
  defense: '防御',
  'special-attack': '特攻',
  'special-defense': '特防',
  speed: '速度'
};

export function PokemonInfo() {
  const [pokemonId, setPokemonId] = useState(25);
  const { data } = useSuspenseQuery(pokemonOptions(pokemonId));

  return (
    <div className='space-y-6'>
      {/* Pokemon selector */}
      <Card>
        <CardHeader>
          <CardTitle>选择宝可梦</CardTitle>
          <CardDescription>
            每次选择都会触发 <code>useSuspenseQuery</code>
            。缓存结果会立即显示，获取新数据时显示加载占位内容。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className='flex flex-wrap gap-2'>
            {POKEMON_IDS.map((id) => (
              <Button
                key={id}
                variant={pokemonId === id ? 'default' : 'outline'}
                size='sm'
                onClick={() => setPokemonId(id)}
              >
                #{id}
              </Button>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Pokemon card */}
      <Card>
        <CardHeader>
          <div className='flex items-center gap-3'>
            <CardTitle>{POKEMON_NAMES[pokemonId] ?? data.name}</CardTitle>
            <div className='flex gap-1'>
              {data.types.map(({ type }) => (
                <Badge key={type.name} variant='secondary'>
                  {TYPE_NAMES[type.name] ?? type.name}
                </Badge>
              ))}
            </div>
          </div>
          <CardDescription>
            身高：{data.height / 10} 米 &middot; 体重：{data.weight / 10} 千克
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className='flex flex-col items-center gap-6 sm:flex-row'>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={data.sprites.front_shiny}
              alt={data.name}
              width={160}
              height={160}
              className='bg-muted/50 rounded-lg'
            />
            <div className='flex-1 space-y-3'>
              {data.stats.map((s) => (
                <div key={s.stat.name} className='space-y-1'>
                  <div className='flex justify-between text-sm'>
                    <span className='text-muted-foreground'>
                      {STAT_NAMES[s.stat.name] ?? s.stat.name}
                    </span>
                    <span className='font-medium'>{s.base_stat}</span>
                  </div>
                  <Progress value={Math.min(s.base_stat, 150) / 1.5} />
                </div>
              ))}
            </div>
          </div>
        </CardContent>
        <CardFooter>
          <p className='text-muted-foreground text-xs'>
            数据来自 PokeAPI &middot; 服务端预取，客户端注水
          </p>
        </CardFooter>
      </Card>
    </div>
  );
}

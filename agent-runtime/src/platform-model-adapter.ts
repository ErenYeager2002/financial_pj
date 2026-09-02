import {
  createModels,
  createProvider,
  type ApiKeyAuth,
  type Model
} from '@earendil-works/pi-ai';
import { openAICompletionsApi } from '@earendil-works/pi-ai/api/openai-completions.lazy';

export interface PlatformModelOptions {
  modelId: string;
  gatewayUrl: string;
  accessToken: string | (() => Promise<string>);
  gatewayFields?: Readonly<Record<string, string>>;
  contextWindow?: number;
  maxTokens?: number;
}

export interface PlatformModelHandle {
  model: Model<'openai-completions'>;
  streamSimple: ReturnType<typeof createModels>['streamSimple'];
}

function checkedGatewayUrl(value: string): string {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error('平台模型网关地址无效。');
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('平台模型网关地址协议不受支持。');
  }
  if (parsed.username || parsed.password || parsed.hash) {
    throw new Error('平台模型网关地址不能包含凭据或片段。');
  }
  return parsed.toString().replace(/\/$/, '');
}

function requestAuth(
  accessToken: string | (() => Promise<string>)
): ApiKeyAuth {
  const resolveToken = typeof accessToken === 'function'
    ? accessToken
    : async () => accessToken;
  return {
    name: '平台会话令牌',
    resolve: async () => {
      const token = await resolveToken();
      if (!token.trim()) throw new Error('平台会话令牌不能为空。');
      return { auth: { apiKey: token } };
    }
  };
}

export function createPlatformModel(options: PlatformModelOptions): PlatformModelHandle {
  if (!options.modelId.trim()) throw new Error('平台模型名称不能为空。');
  if (typeof options.accessToken === 'string' && !options.accessToken.trim()) {
    throw new Error('平台会话令牌不能为空。');
  }

  const model: Model<'openai-completions'> = {
    id: options.modelId,
    name: options.modelId,
    api: 'openai-completions',
    provider: 'financial-platform',
    baseUrl: checkedGatewayUrl(options.gatewayUrl),
    reasoning: false,
    input: ['text'],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: options.contextWindow ?? 128000,
    maxTokens: options.maxTokens ?? 4096,
    compat: {
      supportsDeveloperRole: false,
      supportsReasoningEffort: false,
      supportsUsageInStreaming: true,
      supportsStrictMode: true
    }
  };

  const provider = createProvider({
    id: 'financial-platform',
    name: '财务平台模型网关',
    auth: { apiKey: requestAuth(options.accessToken) },
    models: [model],
    api: openAICompletionsApi()
  });
  const models = createModels();
  models.setProvider(provider);
  const selected = models.getModel('financial-platform', options.modelId);
  if (!selected) throw new Error('平台模型没有成功注册。');
  const streamSimple: PlatformModelHandle['streamSimple'] = (
    currentModel,
    context,
    streamOptions
  ) => {
    const callerOnPayload = streamOptions?.onPayload;
    return models.streamSimple(currentModel, context, {
      ...streamOptions,
      onPayload: (payload, payloadModel) => {
        const gatewayPayload = { ...(payload as Record<string, unknown>) };
        delete gatewayPayload.store;
        delete gatewayPayload.prompt_cache_key;
        delete gatewayPayload.prompt_cache_retention;
        return callerOnPayload
          ? callerOnPayload(gatewayPayload as never, payloadModel)
          : gatewayPayload;
      },
      samplingParams: {
        ...(streamOptions?.samplingParams ?? {}),
        ...(options.gatewayFields ?? {})
      }
    });
  };
  return {
    // The provider above is constructed with exactly one openai-completions
    // model. The registry widens its return type to Model<Api>, so narrow it
    // only after the successful lookup.
    model: selected as Model<'openai-completions'>,
    streamSimple
  };
}

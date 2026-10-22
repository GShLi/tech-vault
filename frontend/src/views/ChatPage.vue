<script setup lang="ts">
import { useProviderSelection } from '@/composables/useProviderSelection'
import {
  ApiRequestError,
  api,
  getAccessToken,
  loadAllPages,
  normalizeApiError as toApiError,
} from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Checkbox as ACheckbox,
  Empty as AEmpty,
  Form as AForm,
  FormItem as AFormItem,
  Input as AInput,
  Message as ArcoMessage,
  Option as AOption,
  Select as ASelect,
  Spin as ASpin,
  Switch as ASwitch,
  Tag as ATag,
  Textarea as ATextarea,
} from '@arco-design/web-vue'

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertTriangle,
  BookOpen,
  ChevronDown,
  MessageSquare,
  Plus,
  Quote,
  RefreshCw,
  Send,
  Square,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  X,
} from 'lucide-vue-next'

import { statusColor } from '@/utils/status'
import { useTeamStore } from '@/stores/team'
import type {
  AskChatInput,
  ChatView,
  CitationView,
  FacetView,
  FeedbackType,
  KnowledgeBase,
  MessageView,
  ModelProvider,
} from '@/types/api'
import { formatDate, shortId, statusLabel } from '@/utils/format'
import { readSseEvents, type ParsedSseEvent } from '@/utils/sse'

interface AskPayload {
  message_id?: string
  chat_id?: string
  content?: string
  citations?: unknown
  citation_ids?: unknown
  trace_id?: string
  status?: string
  refusal_reason?: string | null
  degraded?: boolean
}

interface AskContext {
  knowledgeBaseIds: string[]
  product: string
  version: string
  providerId: string
  modelId: string
}

interface FeedbackState {
  pending: boolean
  selected?: FeedbackType
}

type MessageSegment =
  | { type: 'text'; text: string }
  | {
      type: 'citation'
      text: string
      citationId: string
      matched: boolean
    }

const feedbackOptions: Array<{
  type: FeedbackType
  label: string
  icon: typeof ThumbsUp
}> = [
  { type: 'useful', label: '有帮助', icon: ThumbsUp },
  { type: 'not_useful', label: '没帮助', icon: ThumbsDown },
  { type: 'citation_error', label: '引用有误', icon: AlertTriangle },
  { type: 'knowledge_gap', label: '知识缺失', icon: BookOpen },
]

const team = useTeamStore()
const route = useRoute()
const router = useRouter()

const chats = ref<ChatView[]>([])
const knowledgeBases = ref<KnowledgeBase[]>([])
const facets = ref<FacetView>({
  products: [],
  versions: [],
  sources: [],
  knowledge_base_ids: [],
})
const currentChat = ref<ChatView | null>(null)
const messages = ref<MessageView[]>([])
const providers = ref<ModelProvider[]>([])
const allowedProviderIds = ref<string[]>([])
const citationsByMessage = ref<Record<string, CitationView[]>>({})
const selectedKbIds = ref<string[]>([])
const selectedProduct = ref('')
const selectedVersion = ref('')
const {
  selectedProviderId,
  selectedModelId,
  eligibleProviders,
  selectedProvider,
  modelOptions,
  hasProviderAndModel,
} = useProviderSelection(providers, allowedProviderIds)
const rewrittenQuestion = ref('')
const newChatTitle = ref('')
const question = ref('')
const error = ref<ApiRequestError | null>(null)
const loadingChats = ref(false)
const loadingKnowledgeBases = ref(false)
const loadingMessages = ref(false)
const loadingMoreMessages = ref(false)
const creatingChat = ref(false)
const sending = ref(false)
const streamEnabled = ref(true)
const degraded = ref(false)
const engineMode = ref('')
const traceId = ref('')
const messageList = ref<HTMLElement | null>(null)
const activeAbort = ref<AbortController | null>(null)
const activeAssistant = ref<MessageView | null>(null)
const stopping = ref(false)
const messageNextCursor = ref<string | null>(null)
const messageHasMore = ref(false)
const feedbackByMessage = ref<Record<string, FeedbackState>>({})
const askContextByMessageId = ref<Record<string, AskContext>>({})
const expandedCitations = ref<Record<string, boolean>>({})
const highlightedCitations = ref<Record<string, boolean>>({})
const citationEntryElements = new Map<string, HTMLElement>()
const citationHighlightTimers = new Map<string, ReturnType<typeof setTimeout>>()
let providerOptionsRequestGeneration = 0
const citationHighlightDurationMs = 1500

const apiBaseUrl = computed(() =>
  (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, ''),
)

const selectedKnowledgeBases = computed(() =>
  knowledgeBases.value.filter((kb) => selectedKbIds.value.includes(kb.id)),
)

const canSubmit = computed(
  () =>
    Boolean(question.value.trim()) &&
    Boolean(team.selectedTeamId) &&
    selectedKbIds.value.length > 0 &&
    hasProviderAndModel.value &&
    !sending.value &&
    !creatingChat.value,
)

const showKnowledgeBaseEmpty = computed(
  () => !loadingKnowledgeBases.value && knowledgeBases.value.length === 0,
)

const latestQuestionPair = computed(() => {
  for (let index = messages.value.length - 1; index >= 0; index -= 1) {
    const user = messages.value[index]
    if (user.role !== 'user') continue
    const assistant = messages.value
      .slice(index + 1)
      .find((message) => message.role === 'assistant')
    if (
      assistant &&
      assistant.status !== 'generating' &&
      isServerMessageId(assistant.id)
    ) {
      return { user, assistant }
    }
  }
  return null
})

const canRegenerate = computed(
  () =>
    Boolean(latestQuestionPair.value) &&
    selectedKbIds.value.length > 0 &&
    hasProviderAndModel.value &&
    !sending.value &&
    !creatingChat.value &&
    !stopping.value,
)

function resetConversationState(): void {
  activeAbort.value?.abort()
  activeAbort.value = null
  activeAssistant.value = null
  stopping.value = false
  sending.value = false
  currentChat.value = null
  messages.value = []
  messageNextCursor.value = null
  messageHasMore.value = false
  citationsByMessage.value = {}
  feedbackByMessage.value = {}
  askContextByMessageId.value = {}
  resetCitationInteractionState()
  degraded.value = false
  engineMode.value = ''
  traceId.value = ''
  rewrittenQuestion.value = ''
  question.value = ''
  error.value = null
}

async function loadKnowledgeBases(): Promise<void> {
  const teamId = team.selectedTeamId
  if (!teamId) {
    knowledgeBases.value = []
    selectedKbIds.value = []
    return
  }
  loadingKnowledgeBases.value = true
  try {
    const rows = await loadAllPages((cursor) =>
      api.listKbs(teamId, cursor, 100),
    )
    knowledgeBases.value = rows.filter((kb) => kb.status === 'active')
    selectedKbIds.value = selectedKbIds.value.filter((id) =>
      knowledgeBases.value.some((kb) => kb.id === id),
    )
    if (!selectedKbIds.value.length && knowledgeBases.value.length) {
      selectedKbIds.value = [knowledgeBases.value[0].id]
    }
  } catch (caught) {
    error.value = toApiError(caught, '无法加载知识库')
  } finally {
    loadingKnowledgeBases.value = false
  }
}

async function loadFacets(): Promise<void> {
  if (!team.selectedTeamId) {
    facets.value = {
      products: [],
      versions: [],
      sources: [],
      knowledge_base_ids: [],
    }
    return
  }
  try {
    const response = await api.listFacets(team.selectedTeamId)
    facets.value = {
      products: Array.isArray(response?.products) ? response.products : [],
      versions: Array.isArray(response?.versions) ? response.versions : [],
      sources: Array.isArray(response?.sources) ? response.sources : [],
      knowledge_base_ids: Array.isArray(response?.knowledge_base_ids)
        ? response.knowledge_base_ids
        : [],
    }
    if (!facets.value.products.includes(selectedProduct.value))
      selectedProduct.value = ''
    if (!facets.value.versions.includes(selectedVersion.value))
      selectedVersion.value = ''
  } catch {
    facets.value = {
      products: [],
      versions: [],
      sources: [],
      knowledge_base_ids: [],
    }
    selectedProduct.value = ''
    selectedVersion.value = ''
  }
}

async function loadProviderOptions(): Promise<void> {
  const requestGeneration = ++providerOptionsRequestGeneration
  const teamId = team.selectedTeamId
  selectedProviderId.value = ''
  selectedModelId.value = ''
  if (!teamId) {
    providers.value = []
    allowedProviderIds.value = []
    return
  }
  providers.value = []
  allowedProviderIds.value = []
  try {
    const [policy, rows] = await Promise.all([
      api.getPolicy(teamId),
      loadAllPages((cursor) => api.listProviders(teamId, cursor, 100)),
    ])
    if (
      requestGeneration !== providerOptionsRequestGeneration ||
      team.selectedTeamId !== teamId
    ) {
      return
    }
    providers.value = rows
    allowedProviderIds.value = Array.isArray(policy.allowed_provider_ids)
      ? policy.allowed_provider_ids
      : []
  } catch (caught) {
    if (
      requestGeneration !== providerOptionsRequestGeneration ||
      team.selectedTeamId !== teamId
    ) {
      return
    }
    providers.value = []
    allowedProviderIds.value = []
    error.value = toApiError(caught, '无法加载供应商和模型')
  }
}

async function loadChats(showLoading = true): Promise<void> {
  const teamId = team.selectedTeamId
  if (!teamId) {
    chats.value = []
    return
  }
  if (showLoading) loadingChats.value = true
  try {
    const rows = await loadAllPages((cursor) =>
      api.listChats(teamId, cursor, 100),
    )
    chats.value = rows
    if (currentChat.value) {
      currentChat.value =
        rows.find((chat) => chat.id === currentChat.value?.id) ??
        currentChat.value
    }

    const routedChatId = String(route.params.chatId ?? '')
    const routedChat = routedChatId
      ? rows.find((chat) => chat.id === routedChatId)
      : null
    if (routedChat && currentChat.value?.id !== routedChat.id) {
      await selectChat(routedChat, false)
    }
  } catch (caught) {
    error.value = toApiError(caught, '无法加载会话')
  } finally {
    if (showLoading) loadingChats.value = false
  }
}

async function initialize(): Promise<void> {
  resetConversationState()
  loadingChats.value = true
  loadingKnowledgeBases.value = true
  try {
    selectedProduct.value = ''
    selectedVersion.value = ''
    await Promise.all([
      loadChats(false),
      loadKnowledgeBases(),
      loadFacets(),
      loadProviderOptions(),
    ])
  } finally {
    loadingChats.value = false
  }
}

async function selectChat(chat: ChatView, syncRoute = true): Promise<void> {
  if (sending.value) return
  resetCitationInteractionState()
  currentChat.value = chat
  selectedKbIds.value = [...chat.knowledge_base_ids]
  if (!selectedKbIds.value.length && knowledgeBases.value.length) {
    selectedKbIds.value = [knowledgeBases.value[0].id]
  }
  messages.value = []
  degraded.value = false
  engineMode.value = ''
  traceId.value = ''
  rewrittenQuestion.value = ''
  error.value = null
  if (syncRoute && route.params.chatId !== chat.id) {
    await router.push(`/chat/${chat.id}`)
  }
  await loadMessages()
}

async function loadMessages(reset = true): Promise<void> {
  if (!team.selectedTeamId || !currentChat.value) return
  if (reset) loadingMessages.value = true
  else loadingMoreMessages.value = true
  error.value = null
  try {
    const page = await api.listMessages(
      team.selectedTeamId,
      currentChat.value.id,
      reset ? null : messageNextCursor.value,
    )
    const existingIds = new Set(messages.value.map((message) => message.id))
    const rows = reset
      ? page.data
      : page.data.filter((message) => !existingIds.has(message.id))
    messages.value = reset ? rows : [...messages.value, ...rows]
    messageNextCursor.value = page.meta.next_cursor
    messageHasMore.value = page.meta.has_more
    await hydrateCitations(rows)
    if (reset) await scrollToLatest(false)
  } catch (caught) {
    error.value = toApiError(
      caught,
      reset ? '无法刷新消息' : '无法加载更多消息',
    )
  } finally {
    if (reset) loadingMessages.value = false
    else loadingMoreMessages.value = false
  }
}

function loadMoreMessages(): Promise<void> {
  return loadMessages(false)
}

function toggleKnowledgeBase(kbId: string): void {
  if (sending.value || creatingChat.value) return
  selectedKbIds.value = selectedKbIds.value.includes(kbId)
    ? selectedKbIds.value.filter((id) => id !== kbId)
    : [...selectedKbIds.value, kbId]
}

async function createChat(): Promise<ChatView | null> {
  if (!team.selectedTeamId || creatingChat.value) return null
  if (!selectedKbIds.value.length) {
    error.value = new ApiRequestError(
      '至少选择一个知识库。',
      'INVALID_ARGUMENT',
    )
    return null
  }
  creatingChat.value = true
  error.value = null
  try {
    const created = await api.createChat(
      team.selectedTeamId,
      newChatTitle.value.trim() || undefined,
      [...selectedKbIds.value],
    )
    chats.value = [
      created,
      ...chats.value.filter((chat) => chat.id !== created.id),
    ]
    currentChat.value = created
    messages.value = []
    newChatTitle.value = ''
    await router.push(`/chat/${created.id}`)
    ArcoMessage.success('会话已创建')
    return created
  } catch (caught) {
    error.value = toApiError(caught, '无法创建会话')
    return null
  } finally {
    creatingChat.value = false
  }
}

async function deleteChat(chat: ChatView): Promise<void> {
  if (!team.selectedTeamId || sending.value) return
  try {
    await api.deleteChat(team.selectedTeamId, chat.id)
    chats.value = chats.value.filter((item) => item.id !== chat.id)
    if (currentChat.value?.id === chat.id) {
      currentChat.value = null
      messages.value = []
      await router.push('/chat')
    }
    ArcoMessage.success('会话已删除')
  } catch (caught) {
    error.value = toApiError(caught, '无法删除会话')
  }
}

function temporaryMessage(
  role: 'user' | 'assistant',
  content: string,
  status: string,
): MessageView {
  return {
    id: `local-${role}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    chat_id: currentChat.value?.id ?? '',
    role,
    content,
    status,
    trace_id: null,
    citation_ids: [],
    refusal_reason: null,
    created_at: new Date().toISOString(),
  }
}

function isServerMessageId(messageId: string): boolean {
  return Boolean(messageId) && !messageId.startsWith('local-')
}

function currentAskContext(): AskContext {
  return {
    knowledgeBaseIds: [...selectedKbIds.value],
    product: selectedProduct.value,
    version: selectedVersion.value,
    providerId: selectedProviderId.value,
    modelId: selectedModelId.value,
  }
}

async function ensureChat(text: string): Promise<ChatView | null> {
  if (currentChat.value) return currentChat.value
  if (!team.selectedTeamId) {
    error.value = new ApiRequestError('请先选择团队。', 'INVALID_ARGUMENT')
    return null
  }
  const created = await api.createChat(team.selectedTeamId, text.slice(0, 40), [
    ...selectedKbIds.value,
  ])
  chats.value = [created, ...chats.value]
  currentChat.value = created
  await router.push(`/chat/${created.id}`)
  return created
}

async function askQuestion(text: string, context: AskContext): Promise<void> {
  if (!text || sending.value || !team.selectedTeamId) return
  if (!context.knowledgeBaseIds.length) {
    error.value = new ApiRequestError(
      '至少选择一个知识库。',
      'INVALID_ARGUMENT',
    )
    return
  }
  if (!context.providerId || !context.modelId) {
    error.value = new ApiRequestError(
      '请选择供应商和模型。',
      'INVALID_ARGUMENT',
    )
    return
  }

  sending.value = true
  error.value = null
  degraded.value = false
  engineMode.value = ''
  traceId.value = ''

  let assistant: MessageView | null = null
  try {
    const chat = await ensureChat(text)
    if (!chat) return

    const user = temporaryMessage('user', text, 'completed')
    assistant = temporaryMessage('assistant', '', 'generating')
    assistant.chat_id = chat.id
    user.chat_id = chat.id
    messages.value.push(user, assistant)
    assistant = messages.value[messages.value.length - 1] as MessageView
    activeAssistant.value = assistant
    askContextByMessageId.value[user.id] = {
      knowledgeBaseIds: [...context.knowledgeBaseIds],
      product: context.product,
      version: context.version,
      providerId: context.providerId,
      modelId: context.modelId,
    }
    citationsByMessage.value[assistant.id] = []
    await scrollToLatest()

    const controller = new AbortController()
    activeAbort.value = controller
    const body: AskChatInput = {
      team_id: team.selectedTeamId,
      chat_id: chat.id,
      provider_id: context.providerId,
      model_id: context.modelId,
      question: text,
      filters: {
        knowledge_base_ids: [...context.knowledgeBaseIds],
        product: context.product || null,
        version_values: context.version ? [context.version] : [],
      },
      model_policy: 'inherit',
      stream: streamEnabled.value,
    }
    const response = await fetch(`${apiBaseUrl.value}/chats/ask`, {
      method: 'POST',
      headers: {
        Accept: streamEnabled.value ? 'text/event-stream' : 'application/json',
        Authorization: `Bearer ${getAccessToken() ?? ''}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    })

    if (!response.ok) throw await responseError(response)
    const contentType = response.headers.get('content-type') ?? ''
    if (contentType.includes('application/json')) {
      const envelope = await response.json()
      applyAnswerPayload(assistant, (envelope?.data ?? envelope) as AskPayload)
    } else {
      const streamingAssistant = assistant
      await readSseEvents(response, (event) =>
        handleStreamEvent(event, streamingAssistant),
      )
    }

    if (!assistant.content.trim()) {
      assistant.content =
        assistant.status === 'refused'
          ? '知识库中没有足够依据。'
          : '未生成回答内容。'
    }
    await scrollToLatest()
    void loadChats(false)
  } catch (caught) {
    const aborted =
      caught instanceof DOMException && caught.name === 'AbortError'
    if (assistant) {
      assistant.status = aborted ? 'cancelled' : 'failed'
      if (aborted) {
        if (!assistant.content.trim()) assistant.content = '已停止生成。'
      } else {
        assistant.content =
          assistant.content || toApiError(caught, '问答请求失败').message
      }
    }
    if (!aborted) error.value = toApiError(caught, '问答请求失败')
  } finally {
    sending.value = false
    activeAbort.value = null
    activeAssistant.value = null
    stopping.value = false
  }
}

async function sendQuestion(): Promise<void> {
  if (!canSubmit.value) return
  const text = question.value.trim()
  question.value = ''
  await askQuestion(text, currentAskContext())
}

async function regenerateLatest(): Promise<void> {
  const pair = latestQuestionPair.value
  if (!pair || sending.value) return
  const storedContext = askContextByMessageId.value[pair.user.id]
  await askQuestion(pair.user.content, {
    knowledgeBaseIds: selectedKbIds.value.length
      ? [...selectedKbIds.value]
      : (storedContext?.knowledgeBaseIds ?? []),
    product: storedContext?.product ?? selectedProduct.value,
    version: storedContext?.version ?? selectedVersion.value,
    providerId: selectedProviderId.value,
    modelId: selectedModelId.value,
  })
}

async function stopGenerating(): Promise<void> {
  if (stopping.value) return
  stopping.value = true
  const assistant = activeAssistant.value
  if (assistant && team.selectedTeamId && isServerMessageId(assistant.id)) {
    try {
      await api.cancelMessage(team.selectedTeamId, assistant.id)
      assistant.status = 'cancelled'
      if (!assistant.content.trim()) assistant.content = '已停止生成。'
      ArcoMessage.success('已停止生成')
    } catch (caught) {
      ArcoMessage.error(toApiError(caught, '无法停止生成').message)
    }
  }
  activeAbort.value?.abort()
  stopping.value = false
}

function feedbackState(messageId: string): FeedbackState | undefined {
  return feedbackByMessage.value[messageId]
}

function feedbackSelected(message: MessageView, type: FeedbackType): boolean {
  return feedbackState(message.id)?.selected === type
}

function canSubmitFeedback(message: MessageView): boolean {
  const state = feedbackState(message.id)
  return (
    message.role === 'assistant' &&
    message.status === 'completed' &&
    isServerMessageId(message.id) &&
    !state?.pending &&
    !state?.selected
  )
}

async function submitMessageFeedback(
  message: MessageView,
  type: FeedbackType,
): Promise<void> {
  if (!team.selectedTeamId || !canSubmitFeedback(message)) return
  feedbackByMessage.value = {
    ...feedbackByMessage.value,
    [message.id]: { pending: true },
  }
  try {
    await api.submitFeedback(team.selectedTeamId, message.id, type)
    feedbackByMessage.value = {
      ...feedbackByMessage.value,
      [message.id]: { pending: false, selected: type },
    }
    ArcoMessage.success('反馈已提交')
  } catch (caught) {
    const next = { ...feedbackByMessage.value }
    delete next[message.id]
    feedbackByMessage.value = next
    ArcoMessage.error(toApiError(caught, '反馈提交失败').message)
  }
}

async function responseError(response: Response): Promise<ApiRequestError> {
  let payload: {
    error?: {
      code?: string
      message?: string
      request_id?: string
      details?: Record<string, unknown>
    }
  } | null = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }
  return new ApiRequestError(
    payload?.error?.message ?? `问答请求失败（HTTP ${response.status}）`,
    payload?.error?.code ?? 'HTTP_ERROR',
    payload?.error?.request_id ?? '',
    response.status,
    payload?.error?.details ?? {},
  )
}

async function handleStreamEvent(
  event: ParsedSseEvent,
  assistant: MessageView,
): Promise<void> {
  const data = event.data
  if (event.event === 'meta') {
    updateAssistantId(assistant, stringValue(data.message_id))
    assistant.trace_id = stringValue(data.trace_id) || assistant.trace_id
    traceId.value = assistant.trace_id ?? ''
    engineMode.value = stringValue(data.engine_mode)
    degraded.value = Boolean(data.degraded)
    return
  }
  if (event.event === 'rewrite') {
    rewrittenQuestion.value = stringValue(data.rewritten)
    return
  }
  if (event.event === 'answer') {
    applyAnswerPayload(assistant, data)
    return
  }
  if (event.event === 'delta') {
    const text = stringValue(data.text ?? data.content)
    if (text) assistant.content += text
    return
  }
  if (event.event === 'citation') {
    appendCitation(assistant, data as CitationView)
    return
  }
  if (event.event === 'refused') {
    updateAssistantId(assistant, stringValue(data.message_id))
    assistant.status = 'refused'
    assistant.content =
      stringValue(data.message) || assistant.content || '知识库中没有足够依据。'
    assistant.refusal_reason =
      stringValue(data.reason_code) || 'INSUFFICIENT_EVIDENCE'
    return
  }
  if (event.event === 'error') {
    throw new ApiRequestError(
      stringValue(data.message) || '问答生成失败。',
      stringValue(data.code) || 'STREAM_ERROR',
      stringValue(data.request_id),
    )
  }
  if (event.event === 'done') {
    updateAssistantId(assistant, stringValue(data.message_id))
    const status = stringValue(data.status)
    if (status) assistant.status = status
    const citationIds = data.citation_ids ?? data.citations
    if (citationIds !== undefined) {
      mergeCitations(assistant, normalizeCitations(citationIds))
    }
    return
  }
}

function applyAnswerPayload(assistant: MessageView, payload: AskPayload): void {
  updateAssistantId(assistant, stringValue(payload.message_id))
  if (typeof payload.content === 'string') assistant.content = payload.content
  if (typeof payload.trace_id === 'string') {
    assistant.trace_id = payload.trace_id
    traceId.value = payload.trace_id
  }
  if (typeof payload.status === 'string') assistant.status = payload.status
  if (payload.refusal_reason !== undefined) {
    assistant.refusal_reason = payload.refusal_reason
  }
  if (payload.citations !== undefined) {
    mergeCitations(assistant, normalizeCitations(payload.citations))
  }
  if (payload.citation_ids !== undefined) {
    mergeCitations(assistant, normalizeCitations(payload.citation_ids))
  }
  if (typeof payload.degraded === 'boolean') degraded.value = payload.degraded
}

function updateAssistantId(assistant: MessageView, nextId: string): void {
  if (!nextId || assistant.id === nextId) return
  const previousId = assistant.id
  const previousCitations = citationsByMessage.value[previousId] ?? []
  assistant.id = nextId
  citationsByMessage.value[nextId] = previousCitations
  delete citationsByMessage.value[previousId]
}

function appendCitation(assistant: MessageView, citation: CitationView): void {
  const existing = citationsByMessage.value[assistant.id] ?? []
  const citationId = citation.citation_id ?? citation.chunk_id
  if (
    citationId &&
    existing.some((item) => (item.citation_id ?? item.chunk_id) === citationId)
  ) {
    return
  }
  citationsByMessage.value[assistant.id] = [...existing, citation]
}

function mergeCitations(
  assistant: MessageView,
  citations: CitationView[],
): void {
  citations.forEach((citation) => appendCitation(assistant, citation))
}

function citationId(citation: CitationView): string {
  return citation.citation_id ?? citation.chunk_id ?? ''
}

function citationStateKey(
  message: MessageView,
  citation: CitationView,
): string {
  return `${message.id}:${citationId(citation)}`
}

function citationDomId(message: MessageView, citation: CitationView): string {
  return `citation-${message.id}-${citationId(citation)}`.replace(
    /[^a-zA-Z0-9_-]/g,
    '-',
  )
}

function citationForToken(
  message: MessageView,
  tokenCitationId: string,
): CitationView | undefined {
  const normalized = tokenCitationId.toLowerCase()
  return citationsFor(message).find(
    (citation) => citation.citation_id?.toLowerCase() === normalized,
  )
}

function messageSegments(message: MessageView): MessageSegment[] {
  if (message.role !== 'assistant')
    return [{ type: 'text', text: message.content }]
  const citationIds = new Set(
    citationsFor(message)
      .map((citation) => citation.citation_id?.toLowerCase())
      .filter((value): value is string => Boolean(value)),
  )
  const segments: MessageSegment[] = []
  let lastIndex = 0
  for (const match of message.content.matchAll(/\[(c\d+)\]/gi)) {
    const index = match.index ?? 0
    if (index > lastIndex) {
      segments.push({
        type: 'text',
        text: message.content.slice(lastIndex, index),
      })
    }
    const tokenCitationId = match[1].toLowerCase()
    segments.push({
      type: 'citation',
      text: match[0],
      citationId: tokenCitationId,
      matched: citationIds.has(tokenCitationId),
    })
    lastIndex = index + match[0].length
  }
  if (lastIndex < message.content.length) {
    segments.push({ type: 'text', text: message.content.slice(lastIndex) })
  }
  return segments
}

function registerCitationEntry(key: string, element: unknown): void {
  if (element instanceof HTMLElement) {
    citationEntryElements.set(key, element)
    return
  }
  citationEntryElements.delete(key)
}

function isCitationExpanded(
  message: MessageView,
  citation: CitationView,
): boolean {
  return Boolean(expandedCitations.value[citationStateKey(message, citation)])
}

function isCitationHighlighted(
  message: MessageView,
  citation: CitationView,
): boolean {
  return Boolean(
    highlightedCitations.value[citationStateKey(message, citation)],
  )
}

function toggleCitation(message: MessageView, citation: CitationView): void {
  const key = citationStateKey(message, citation)
  expandedCitations.value = {
    ...expandedCitations.value,
    [key]: !expandedCitations.value[key],
  }
}

function highlightCitation(key: string): void {
  const currentTimer = citationHighlightTimers.get(key)
  if (currentTimer) clearTimeout(currentTimer)
  highlightedCitations.value = {
    ...highlightedCitations.value,
    [key]: true,
  }
  const timer = setTimeout(() => {
    const next = { ...highlightedCitations.value }
    delete next[key]
    highlightedCitations.value = next
    citationHighlightTimers.delete(key)
  }, citationHighlightDurationMs)
  citationHighlightTimers.set(key, timer)
}

async function activateCitation(
  message: MessageView,
  tokenCitationId: string,
): Promise<void> {
  const citation = citationForToken(message, tokenCitationId)
  if (!citation) return
  const key = citationStateKey(message, citation)
  expandedCitations.value = {
    ...expandedCitations.value,
    [key]: true,
  }
  await nextTick()
  const entry = citationEntryElements.get(key)
  if (!entry) return
  entry.scrollIntoView({
    behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
      ? 'auto'
      : 'smooth',
    block: 'center',
  })
  highlightCitation(key)
}

function resetCitationInteractionState(): void {
  citationHighlightTimers.forEach((timer) => clearTimeout(timer))
  citationHighlightTimers.clear()
  citationEntryElements.clear()
  expandedCitations.value = {}
  highlightedCitations.value = {}
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function normalizeCitations(value: unknown): CitationView[] {
  if (Array.isArray(value)) {
    return value.flatMap((item) => normalizeCitations(item))
  }
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed) return []
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      try {
        return normalizeCitations(JSON.parse(trimmed))
      } catch {
        // Fall through to a citation-id-only view.
      }
    }
    return [{ citation_id: trimmed }]
  }
  if (value && typeof value === 'object') return [value as CitationView]
  return []
}

function citationsFor(message: MessageView): CitationView[] {
  return (
    citationsByMessage.value[message.id] ??
    normalizeCitations([
      message.citations,
      message.citation,
      message.citation_ids,
    ])
  )
}

async function hydrateCitations(rows: MessageView[]): Promise<void> {
  if (!team.selectedTeamId) return
  await Promise.all(
    rows.map(async (message) => {
      if (message.role !== 'assistant') return
      const current = citationsFor(message)
      if (!current.length) return
      if (current.some((item) => item.excerpt || item.source_locator)) {
        citationsByMessage.value[message.id] = current
        return
      }
      try {
        const query = new URLSearchParams({
          team_id: team.selectedTeamId ?? '',
          message_id: message.id,
        })
        const response = await fetch(
          `${apiBaseUrl.value}/messages/citations?${query.toString()}`,
          {
            headers: { Authorization: `Bearer ${getAccessToken() ?? ''}` },
          },
        )
        if (!response.ok) return
        const envelope = await response.json()
        const details = normalizeCitations(envelope?.data ?? envelope)
        if (details.length) citationsByMessage.value[message.id] = details
      } catch {
        // The answer remains useful when citation hydration is unavailable.
      }
    }),
  )
}

async function refreshCurrent(): Promise<void> {
  if (!currentChat.value) {
    await initialize()
    return
  }
  await Promise.all([loadMessages(), loadChats(false)])
}

async function scrollToLatest(smooth = true): Promise<void> {
  await nextTick()
  messageList.value?.scrollIntoView?.({
    behavior: smooth ? 'smooth' : 'auto',
    block: 'end',
  })
}

function citationHeading(citation: CitationView): string {
  if (citation.document_name) return citation.document_name
  const fileName = citation.source_locator?.file_name
  if (typeof fileName === 'string') return fileName
  if (citation.chunk_id) return `Chunk ${shortId(citation.chunk_id)}`
  return citation.citation_id ?? '引用'
}

function citationContext(citation: CitationView): string {
  const headingPath =
    citation.heading_path ??
    (Array.isArray(citation.source_locator?.heading_path)
      ? (citation.source_locator.heading_path as string[])
      : [])
  if (headingPath.length) return headingPath.join(' / ')
  const path = citation.source_locator?.path
  if (typeof path === 'string') return path
  if (citation.page_no) return `第 ${citation.page_no} 页`
  const pageNo = citation.source_locator?.page_no
  return typeof pageNo === 'number' ? `第 ${pageNo} 页` : ''
}

function refusalLabel(message: MessageView): string {
  if (message.refusal_reason === 'INSUFFICIENT_EVIDENCE') return '依据不足'
  return message.refusal_reason || '已拒答'
}

function isGenerating(message: MessageView): boolean {
  return message.status === 'generating'
}

onMounted(initialize)
onBeforeUnmount(resetCitationInteractionState)

watch(selectedProviderId, () => {
  selectedModelId.value = ''
})

watch(
  () => team.selectedTeamId,
  () => {
    void initialize()
  },
)

watch(
  () => route.params.chatId,
  async (value) => {
    const chatId = String(value ?? '')
    if (!chatId) {
      if (!sending.value) {
        currentChat.value = null
        messages.value = []
      }
      return
    }
    if (currentChat.value?.id === chatId) return
    const routedChat = chats.value.find((chat) => chat.id === chatId)
    if (routedChat) await selectChat(routedChat, false)
  },
)
</script>

<template>
  <div class="chat-workbench">
    <aside class="chat-sidebar panel">
      <div class="session-heading">
        <div>
          <h2>会话</h2>
          <span>{{ chats.length }}</span>
        </div>
        <a-button
          title="刷新会话"
          :disabled="loadingChats"
          @click="loadChats()"
          type="text"
          html-type="button"
          shape="square"
          aria-label="刷新会话"
        >
          <RefreshCw :size="16" :class="{ spinning: loadingChats }" />
        </a-button>
      </div>

      <a-form
        class="new-chat-form"
        :model="{ newChatTitle }"
        layout="vertical"
        @submit-success="createChat"
      >
        <a-input
          v-model="newChatTitle"
          data-testid="chat-new-title"
          placeholder="新对话标题"
          type="text"
          :max-length="200"
          :input-attrs="{ 'aria-label': '新对话标题' }"
        ></a-input>
        <a-button
          data-testid="chat-create"
          title="创建会话"
          :disabled="creatingChat || !selectedKbIds.length"
          @click="createChat"
          type="primary"
          html-type="button"
        >
          <Plus :size="16" />
        </a-button>
      </a-form>

      <div v-if="loadingChats && !chats.length" class="sidebar-loading">
        <a-spin></a-spin>
        <span>加载会话</span>
      </div>
      <div v-else-if="chats.length" class="session-list">
        <div
          v-for="chat in chats"
          :key="chat.id"
          class="session-item"
          :class="{ active: currentChat?.id === chat.id }"
        >
          <a-button
            :aria-current="currentChat?.id === chat.id ? 'page' : undefined"
            @click="selectChat(chat)"
            type="text"
            html-type="button"
            class="session-select"
          >
            <MessageSquare :size="15" />
            <span>
              <strong>{{ chat.title }}</strong>
              <small>{{ formatDate(chat.updated_at) }}</small>
            </span>
          </a-button>
          <a-button
            title="删除会话"
            :disabled="sending"
            @click="deleteChat(chat)"
            type="text"
            html-type="button"
            class="session-delete"
            shape="square"
            aria-label="删除会话"
          >
            <Trash2 :size="14" />
          </a-button>
        </div>
      </div>
      <a-empty v-else class="page-empty">
        <template #image><MessageSquare :size="22" /></template>
        <span>暂无会话</span>
      </a-empty>
    </aside>

    <section class="chat-main panel">
      <header class="chat-header">
        <div class="chat-heading">
          <div class="chat-title-row">
            <MessageSquare :size="19" />
            <h2>{{ currentChat?.title ?? '新对话' }}</h2>
            <a-tag v-if="degraded" :color="statusColor('degraded')">
              {{ statusLabel('degraded') }}
            </a-tag>
            <a-tag
              v-if="engineMode && !degraded"
              :color="statusColor(engineMode)"
            >
              {{ engineMode === 'dual_engine' ? '双引擎' : 'ES 单引擎' }}
            </a-tag>
          </div>
          <div
            v-if="knowledgeBases.length"
            class="kb-scope"
            aria-label="知识库范围"
          >
            <span>知识库</span>
            <a-checkbox
              v-for="kb in knowledgeBases"
              :key="kb.id"
              :data-testid="`chat-kb-${kb.id}`"
              :disabled="sending"
              :model-value="selectedKbIds.includes(kb.id)"
              @change="toggleKnowledgeBase(kb.id)"
            >
              {{ kb.name }}
            </a-checkbox>
          </div>
          <div
            class="chat-filter-row"
            aria-label="供应商、模型、产品和版本筛选"
          >
            <a-form-item class="chat-filter-field chat-provider-field">
              <template #label>供应商</template>
              <a-select
                v-model="selectedProviderId"
                data-testid="chat-provider-select"
                :disabled="sending || !eligibleProviders.length"
              >
                <a-option value="">选择供应商</a-option>
                <a-option
                  v-for="provider in eligibleProviders"
                  :key="provider.id"
                  :value="provider.id"
                >
                  {{ provider.name }}
                </a-option>
              </a-select>
            </a-form-item>
            <a-form-item class="chat-filter-field chat-provider-field">
              <template #label>模型</template>
              <a-select
                v-model="selectedModelId"
                data-testid="chat-model-select"
                :disabled="sending || !selectedProvider"
              >
                <a-option value="">选择模型</a-option>
                <a-option
                  v-for="model in modelOptions"
                  :key="model"
                  :value="model"
                >
                  {{ model }}
                </a-option>
              </a-select>
            </a-form-item>
            <a-form-item class="chat-filter-field">
              <template #label>产品</template>
              <a-select
                v-model="selectedProduct"
                data-testid="chat-product-filter"
                :disabled="sending"
              >
                <a-option value="">全部产品</a-option>
                <a-option
                  v-for="product in facets.products"
                  :key="product"
                  :value="product"
                >
                  {{ product }}
                </a-option>
              </a-select>
            </a-form-item>
            <a-form-item class="chat-filter-field">
              <template #label>版本</template>
              <a-select
                v-model="selectedVersion"
                data-testid="chat-version-filter"
                :disabled="sending"
              >
                <a-option value="">全部版本</a-option>
                <a-option
                  v-for="version in facets.versions"
                  :key="version"
                  :value="version"
                >
                  {{ version }}
                </a-option>
              </a-select>
            </a-form-item>
          </div>
          <p
            v-if="rewrittenQuestion"
            class="rewrite-note"
            data-testid="chat-rewrite"
          >
            检索改写：{{ rewrittenQuestion }}
          </p>
        </div>
        <div class="chat-actions">
          <div class="stream-switch">
            <a-switch
              v-model="streamEnabled"
              data-testid="chat-stream-toggle"
              :disabled="sending"
              aria-label="流式输出"
            ></a-switch>
            <span>流式</span>
          </div>
          <a-button
            data-testid="chat-regenerate"
            :disabled="!canRegenerate"
            @click="regenerateLatest"
            type="secondary"
            html-type="button"
          >
            <RefreshCw :size="15" />
            重新生成
          </a-button>
          <a-button
            data-testid="chat-refresh"
            title="刷新消息"
            :disabled="!currentChat || loadingMessages || sending"
            @click="refreshCurrent"
            type="text"
            html-type="button"
            shape="square"
            aria-label="刷新消息"
          >
            <RefreshCw :size="17" :class="{ spinning: loadingMessages }" />
          </a-button>
        </div>
      </header>

      <a-alert v-if="error" type="error" class="page-alert">
        <AlertTriangle :size="17" />
        <div>
          <strong>{{ error.message }}</strong>
          <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
        </div>
        <a-button
          title="关闭错误"
          @click="error = null"
          type="text"
          html-type="button"
          shape="square"
          aria-label="关闭错误"
        >
          <X :size="15" />
        </a-button>
      </a-alert>

      <div ref="messageList" class="message-scroll" aria-live="polite">
        <div v-if="loadingMessages && !messages.length" class="chat-loading">
          <a-spin></a-spin>
          <span>正在加载消息</span>
        </div>

        <div v-else-if="showKnowledgeBaseEmpty" class="chat-empty">
          <BookOpen :size="30" />
          <h3>当前团队暂无可用知识库</h3>
          <RouterLink to="/knowledge-bases" custom v-slot="{ href, navigate }">
            <a-button type="secondary" :href="href" @click="navigate">
              前往知识库
            </a-button>
          </RouterLink>
        </div>

        <div v-else-if="messages.length" class="message-list">
          <div
            v-if="messageHasMore"
            class="load-more"
            data-testid="chat-load-more"
          >
            <a-button
              :disabled="loadingMoreMessages"
              @click="loadMoreMessages"
              type="secondary"
              html-type="button"
            >
              {{ loadingMoreMessages ? '加载中' : '继续加载' }}
            </a-button>
          </div>
          <article
            v-for="message in messages"
            :key="message.id"
            class="message-row"
            :class="message.role"
          >
            <div class="message-role">
              {{ message.role === 'user' ? '你' : '助手' }}
            </div>
            <div class="message-bubble">
              <div
                v-if="isGenerating(message) && !message.content"
                class="answer-loading"
              >
                <span class="typing-dot" />
                <span class="typing-dot" />
                <span class="typing-dot" />
                <span>正在检索</span>
              </div>
              <div
                v-else-if="message.role === 'assistant'"
                class="message-content"
              >
                <template
                  v-for="(segment, segmentIndex) in messageSegments(message)"
                  :key="`${message.id}-segment-${segmentIndex}`"
                >
                  <span v-if="segment.type === 'text'">{{ segment.text }}</span>
                  <a-button
                    v-else-if="segment.matched"
                    :data-testid="`inline-citation-${segment.citationId}`"
                    :aria-label="`查看引用 ${segment.text}`"
                    @click="activateCitation(message, segment.citationId)"
                    type="secondary"
                    html-type="button"
                    class="citation-token"
                  >
                    {{ segment.text }}
                  </a-button>
                  <span
                    v-else
                    class="citation-token citation-token-unavailable"
                    :data-testid="`inline-citation-unavailable-${segment.citationId}`"
                    aria-disabled="true"
                    title="引用不可用"
                  >
                    {{ segment.text }}
                  </span>
                </template>
              </div>
              <div v-else class="message-content">{{ message.content }}</div>

              <div v-if="message.status === 'refused'" class="refusal-note">
                <AlertTriangle :size="16" />
                <div>
                  <strong>{{ refusalLabel(message) }}</strong>
                  <span>{{ message.content }}</span>
                </div>
              </div>

              <div
                v-if="
                  message.role === 'assistant' && citationsFor(message).length
                "
                class="citation-list"
              >
                <div class="citation-heading">
                  <Quote :size="15" />
                  <span>引用</span>
                </div>
                <article
                  v-for="citation in citationsFor(message)"
                  :key="citation.citation_id ?? citation.chunk_id"
                  class="citation-item"
                  :ref="
                    (element) =>
                      registerCitationEntry(
                        citationStateKey(message, citation),
                        element,
                      )
                  "
                >
                  <a-button
                    :class="{
                      'citation-item-highlighted': isCitationHighlighted(
                        message,
                        citation,
                      ),
                    }"
                    :data-testid="`citation-entry-${citationId(citation)}`"
                    :aria-expanded="isCitationExpanded(message, citation)"
                    :aria-controls="citationDomId(message, citation)"
                    @click="toggleCitation(message, citation)"
                    type="secondary"
                    html-type="button"
                    class="citation-entry"
                  >
                    <span class="citation-title">
                      <strong>{{ citationHeading(citation) }}</strong>
                      <span v-if="citationContext(citation)">
                        {{ citationContext(citation) }}
                      </span>
                    </span>
                    <span class="citation-reference">
                      {{ citationId(citation) }}
                    </span>
                    <ChevronDown
                      :size="14"
                      class="citation-chevron"
                      :class="{
                        expanded: isCitationExpanded(message, citation),
                      }"
                    />
                  </a-button>
                  <div
                    v-if="isCitationExpanded(message, citation)"
                    :id="citationDomId(message, citation)"
                    class="citation-details"
                    :data-testid="`citation-details-${citationId(citation)}`"
                  >
                    <p v-if="citation.excerpt">{{ citation.excerpt }}</p>
                    <a
                      v-if="citation.source_url"
                      :href="citation.source_url"
                      target="_blank"
                      rel="noreferrer"
                    >
                      查看来源
                    </a>
                  </div>
                </article>
              </div>

              <div
                v-if="
                  message.role === 'assistant' && message.status === 'completed'
                "
                class="feedback-bar"
                aria-label="回答反馈"
              >
                <span>反馈</span>
                <a-button
                  v-for="option in feedbackOptions"
                  :key="option.type"
                  :class="{ selected: feedbackSelected(message, option.type) }"
                  :data-testid="`chat-feedback-${option.type}-${message.id}`"
                  :aria-pressed="feedbackSelected(message, option.type)"
                  :disabled="!canSubmitFeedback(message)"
                  @click="submitMessageFeedback(message, option.type)"
                  type="text"
                  html-type="button"
                  class="feedback-button"
                >
                  <component :is="option.icon" :size="13" />
                  {{ option.label }}
                </a-button>
              </div>

              <footer class="message-meta">
                <span>{{ formatDate(message.created_at) }}</span>
                <span v-if="message.trace_id" class="trace-reference">
                  Trace {{ shortId(message.trace_id) }}
                </span>
                <a-tag
                  v-if="message.role === 'assistant'"
                  :color="statusColor(message.status)"
                >
                  {{ statusLabel(message.status) }}
                </a-tag>
              </footer>
            </div>
          </article>
        </div>

        <a-empty v-else class="page-empty">
          <template #image><MessageSquare :size="30" /></template>
          <h3>{{ currentChat ? '当前会话暂无消息' : '新对话' }}</h3>
          <p v-if="selectedKnowledgeBases.length">
            {{ selectedKnowledgeBases.map((kb) => kb.name).join('、') }}
          </p>
        </a-empty>
      </div>

      <a-form
        class="composer"
        :model="{ question }"
        layout="vertical"
        @submit-success="sendQuestion"
      >
        <a-textarea
          v-model="question"
          data-testid="question-input"
          placeholder="输入问题"
          :disabled="sending || showKnowledgeBaseEmpty"
          @keydown.enter.exact.prevent="sendQuestion"
          :max-length="4000"
          :textarea-attrs="{ 'aria-label': '问题输入', rows: '3' }"
        ></a-textarea>
        <div class="composer-footer">
          <span v-if="selectedKnowledgeBases.length" class="composer-scope">
            {{ selectedKnowledgeBases.length }} 个知识库
          </span>
          <span v-else class="composer-scope warning-text">未选择知识库</span>
          <a-button
            v-if="sending"
            data-testid="chat-stop"
            :disabled="stopping"
            @click="stopGenerating"
            type="secondary"
            html-type="button"
            status="danger"
          >
            <Square :size="14" />
            {{ stopping ? '停止中' : '停止' }}
          </a-button>
          <a-button
            v-else
            data-testid="send-message"
            :disabled="!canSubmit"
            @click="sendQuestion"
            type="primary"
            html-type="button"
            class="chat-send-button"
          >
            <Send :size="16" />
            发送
          </a-button>
        </div>
      </a-form>
    </section>
  </div>
</template>

<style scoped>
.chat-workbench {
  display: grid;
  min-height: 620px;
  height: calc(100vh - 156px);
  grid-template-columns: 264px minmax(0, 1fr);
  gap: 14px;
}

.chat-sidebar,
.chat-main {
  min-height: 0;
  overflow: hidden;
}

.chat-sidebar {
  display: flex;
  flex-direction: column;
}

.session-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px;
  border-bottom: 1px solid #edf0f3;
}

.session-heading > div {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.session-heading h2,
.chat-title-row h2 {
  margin: 0;
  color: var(--text);
}

.session-heading h2 {
  font-size: 16px;
}

.session-heading span {
  color: var(--muted);
  font-size: 12px;
}

.new-chat-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 7px;
  padding: 12px 16px;
  border-bottom: 1px solid #edf0f3;
}

.session-list {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.session-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 30px;
  align-items: center;
  border-radius: 7px;
  color: #334155;
}

.session-item:hover,
.session-item.active {
  background: #eef7f5;
}

.session-item.active {
  color: var(--accent-strong);
}

.session-select {
  height: auto;
  white-space: normal;
  display: flex;
  min-width: 0;
  align-items: flex-start;
  gap: 9px;
  border: 0;
  background: transparent;
  color: inherit;
  padding: 10px 6px 10px 10px;
  text-align: left;
}

.session-select > svg {
  flex: 0 0 auto;
  margin-top: 2px;
}

.session-select > span {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.session-select strong,
.session-select small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-select strong {
  font-size: 13px;
  font-weight: 600;
}

.session-select small {
  color: var(--muted);
  font-size: 10px;
}

.session-delete {
  width: 28px;
  height: 28px;
  color: #94a3b8;
  opacity: 0;
}

.session-item:hover .session-delete,
.session-item.active .session-delete,
.session-delete:focus-visible {
  opacity: 1;
}

.sidebar-loading {
  display: grid;
  flex: 1;
  align-content: center;
  justify-items: center;
  gap: 8px;
  color: var(--muted);
  font-size: 12px;
}

.chat-main {
  display: flex;
  flex-direction: column;
  padding: 0;
}

.chat-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 15px 18px;
  border-bottom: 1px solid #edf0f3;
}

.chat-heading {
  display: grid;
  min-width: 0;
  gap: 11px;
}

.chat-title-row {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
}

.chat-title-row h2 {
  overflow: hidden;
  font-size: 16px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-scope {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.kb-scope > span {
  margin-right: 2px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 600;
}

.chat-filter-row {
  display: flex;
  min-width: 0;
  align-items: end;
  flex-wrap: wrap;
  gap: 8px;
}

.chat-filter-field {
  display: grid;
  min-width: 132px;
  gap: 4px;
  color: var(--muted);
  font-size: 10px;
  font-weight: 650;
}

.rewrite-note {
  margin: 0;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.chat-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 7px;
}

.stream-switch {
  display: inline-flex;
  height: 34px;
  align-items: center;
  gap: 6px;
  padding: 0 9px;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--muted);
  font-size: 12px;
}

.message-scroll {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  scroll-behavior: smooth;
}

.message-list {
  display: grid;
  gap: 18px;
  padding: 22px 24px;
}

.message-row {
  display: grid;
  gap: 6px;
  justify-items: start;
}

.message-row.user {
  justify-items: end;
}

.message-role {
  color: var(--muted);
  font-size: 11px;
  font-weight: 600;
}

.message-bubble {
  width: min(760px, 88%);
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fbfcfd;
  padding: 13px 14px;
}

.message-row.user .message-bubble {
  border-color: #b9ddd7;
  background: #f0faf7;
}

.message-content {
  color: var(--text);
  font-size: 14px;
  line-height: 1.7;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.citation-token {
  display: inline-flex;
  min-height: 20px;
  align-items: baseline;
  justify-content: center;
  margin: 0 1px;
  padding: 0 4px;
  border: 1px solid #a7d8d0;
  border-radius: 4px;
  background: #effaf7;
  color: #0f766e;
  font-family: inherit;
  font-size: 0.82em;
  font-weight: 700;
  line-height: 1.35;
  vertical-align: baseline;
  cursor: pointer;
  transition:
    background 120ms ease,
    border-color 120ms ease;
}

.citation-token:hover {
  border-color: #5fb9aa;
  background: #dcf5ef;
}

.citation-token:focus-visible,
.citation-entry:focus-visible {
  outline: 2px solid #0f766e;
  outline-offset: 2px;
}

.citation-token-unavailable {
  border-color: #d7dde5;
  background: #f6f7f9;
  color: #8792a2;
  cursor: not-allowed;
}

.answer-loading {
  display: flex;
  align-items: center;
  gap: 5px;
  min-height: 26px;
  color: var(--muted);
  font-size: 12px;
}

.answer-loading span:last-child {
  margin-left: 4px;
}

.typing-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #7f8c99;
  animation: typing 1.1s ease-in-out infinite;
}

.typing-dot:nth-child(2) {
  animation-delay: 0.15s;
}

.typing-dot:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes typing {
  0%,
  100% {
    opacity: 0.35;
    transform: translateY(0);
  }
  50% {
    opacity: 1;
    transform: translateY(-2px);
  }
}

.refusal-note {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 10px;
  border-left: 3px solid #d97706;
  background: var(--warning-soft);
  color: #92400e;
  padding: 8px 10px;
}

.refusal-note div {
  display: grid;
  gap: 2px;
  font-size: 12px;
}

.citation-list {
  display: grid;
  gap: 8px;
  margin-top: 13px;
  padding-top: 10px;
  border-top: 1px solid #e5eaf0;
}

.citation-heading {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 650;
  text-transform: uppercase;
}

.citation-item {
  border-left: 2px solid #b8ddd7;
  padding-left: 10px;
  border-radius: 0 6px 6px 0;
}

.citation-item-highlighted {
  animation: citation-pulse 1.5s ease-out;
}

.citation-entry {
  display: grid;
  width: 100%;
  min-height: 32px;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 7px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  padding: 4px 5px;
  text-align: left;
  cursor: pointer;
}

.citation-entry:hover {
  background: #f3f8f7;
}

.citation-title {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 7px;
}

.citation-title strong {
  color: #334155;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.citation-title span,
.citation-reference,
.citation-details p,
.citation-details a {
  color: var(--muted);
  font-size: 11px;
}

.citation-reference {
  color: #0f766e;
  font-weight: 700;
  white-space: nowrap;
}

.citation-chevron {
  flex: 0 0 auto;
  color: var(--muted);
  transition: transform 140ms ease;
}

.citation-chevron.expanded {
  transform: rotate(180deg);
}

.citation-details {
  display: grid;
  gap: 7px;
  margin: 2px 4px 5px;
  border-top: 1px solid #dce9e6;
  padding: 8px 7px 3px;
}

.citation-details p {
  margin: 0;
  line-height: 1.55;
}

.citation-details a {
  width: fit-content;
  color: #0f766e;
  font-weight: 650;
  text-decoration: underline;
  text-underline-offset: 2px;
}

@keyframes citation-pulse {
  0% {
    background: #d9f4ee;
    box-shadow: 0 0 0 2px rgb(15 118 110 / 18%);
  }
  72% {
    background: #eef9f6;
    box-shadow: 0 0 0 1px rgb(15 118 110 / 8%);
  }
  100% {
    background: transparent;
    box-shadow: none;
  }
}

.feedback-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid #e5eaf0;
}

.feedback-bar > span {
  margin-right: 2px;
  color: var(--muted);
  font-size: 10px;
  font-weight: 650;
}

.feedback-button {
  display: inline-flex;
  min-height: 27px;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: #fff;
  color: #64748b;
  padding: 0 8px;
  font-size: 10px;
}

.feedback-button:hover:not(:disabled),
.feedback-button.selected {
  border-color: #7cc7bd;
  background: #ecfdf5;
  color: var(--accent-strong);
}

.feedback-button:disabled {
  cursor: default;
  opacity: 0.72;
}

.message-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 7px;
  margin-top: 10px;
  color: var(--muted);
  font-size: 10px;
}

.trace-reference {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.chat-loading,
.chat-empty {
  display: grid;
  min-height: 100%;
  align-content: center;
  justify-items: center;
  gap: 9px;
  color: var(--muted);
  padding: 30px;
  text-align: center;
}

.chat-loading {
  font-size: 12px;
}

.chat-empty h3,
.chat-empty p {
  margin: 0;
}

.chat-empty h3 {
  color: var(--text);
  font-size: 16px;
}

.chat-empty p {
  font-size: 13px;
}

.chat-empty-ready {
  align-content: start;
  padding-top: 72px;
}

.composer {
  display: grid;
  gap: 8px;
  border-top: 1px solid #edf0f3;
  background: #fff;
  padding: 13px 18px 16px;
}

.composer-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.composer-scope {
  margin-right: auto;
  color: var(--muted);
  font-size: 11px;
}

.warning-text {
  color: #b45309;
}

.spinning {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 900px) {
  .chat-workbench {
    height: auto;
    min-height: 0;
    grid-template-columns: 1fr;
  }

  .chat-sidebar {
    max-height: 250px;
  }

  .chat-main {
    min-height: 620px;
  }

  .chat-header {
    flex-direction: column;
  }

  .chat-actions {
    width: 100%;
    justify-content: flex-end;
  }

  .chat-filter-row,
  .chat-filter-field {
    width: 100%;
  }

  .message-bubble {
    width: 94%;
  }
}

@media (max-width: 560px) {
  .message-list {
    padding: 16px 12px;
  }

  .message-bubble {
    width: 100%;
  }

  .chat-main {
    min-height: 560px;
  }

  .composer-footer {
    align-items: flex-end;
  }

  .chat-filter-row {
    display: grid;
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
  .citation-token,
  .citation-chevron {
    transition: none;
  }

  .citation-item-highlighted {
    animation: none;
    background: #e8f7f3;
    box-shadow: inset 0 0 0 1px rgb(15 118 110 / 18%);
  }
}
</style>

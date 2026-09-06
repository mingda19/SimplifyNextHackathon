import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { Banner } from '../components/ui'

// Deliberately the plainest screen in the app. The person using it may be
// elderly, may not read English, and may be on a borrowed phone. One box, one
// button, large type, no navigation to get lost in.
const COPY = {
  en: { title: 'Tell us what you need', hint: 'Write in any language. We will read it.',
        ph: 'For example: we ran out of rice, and my mother cannot eat hard food',
        send: 'Send request', mic: 'Speak instead', stop: 'Stop recording',
        thanks: 'Thank you — we have received your message.', again: 'Send another' },
  zh: { title: '告诉我们您需要什么', hint: '可以用任何语言书写。',
        ph: '例如：家里的米吃完了，我妈妈牙齿不好',
        send: '发送请求', mic: '改用语音', stop: '停止录音',
        thanks: '谢谢您，我们已收到您的信息。', again: '再发一条' },
  ms: { title: 'Beritahu kami apa yang anda perlukan', hint: 'Tulis dalam bahasa apa pun.',
        ph: 'Contoh: beras kami sudah habis',
        send: 'Hantar permintaan', mic: 'Guna suara', stop: 'Berhenti merakam',
        thanks: 'Terima kasih — kami telah menerima mesej anda.', again: 'Hantar lagi' },
  ta: { title: 'உங்களுக்கு என்ன தேவை என்று சொல்லுங்கள்', hint: 'எந்த மொழியிலும் எழுதலாம்.',
        ph: 'உதாரணம்: வீட்டில் அரிசி தீர்ந்துவிட்டது',
        send: 'அனுப்பு', mic: 'குரல் மூலம்', stop: 'நிறுத்து',
        thanks: 'நன்றி — உங்கள் செய்தி கிடைத்தது.', again: 'மீண்டும் அனுப்பு' },
}

export default function RequestPage() {
  const { token } = useParams()
  const { user, logout } = useAuth()
  const nav = useNavigate()
  const [lang, setLang] = useState('en')
  const [text, setText] = useState('')
  const [sent, setSent] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [link, setLink] = useState(null)
  const [linkBad, setLinkBad] = useState(false)
  const [recording, setRecording] = useState(false)
  const [voiceUnsupported, setVoiceUnsupported] = useState(false)
  const recog = useRef(null)
  const t = COPY[lang]

  useEffect(() => {
    if (!token) return
    api.resolveLink(token).then(setLink).catch(() => setLinkBad(true))
  }, [token])

  // Browser speech recognition. Not available everywhere (Safari/Firefox vary),
  // so the button only appears when the API actually exists — an elderly user
  // tapping a dead button is worse than not offering it.
  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) { setVoiceUnsupported(true); return }
    const r = new SR()
    r.continuous = true
    r.interimResults = true
    r.onresult = e => {
      let final = ''
      for (let i = e.resultIndex; i < e.results.length; i++)
        if (e.results[i].isFinal) final += e.results[i][0].transcript
      if (final) setText(prev => (prev ? prev + ' ' : '') + final.trim())
    }
    r.onend = () => setRecording(false)
    r.onerror = () => { setRecording(false); setErr('Could not hear anything. Please try typing.') }
    recog.current = r
    return () => { try { r.stop() } catch {} }
  }, [])

  useEffect(() => {
    if (!recog.current) return
    recog.current.lang = { en: 'en-SG', zh: 'zh-CN', ms: 'ms-MY', ta: 'ta-IN' }[lang]
  }, [lang])

  const toggleMic = () => {
    const r = recog.current
    if (!r) return
    if (recording) { r.stop(); setRecording(false) }
    else { setErr(''); try { r.start(); setRecording(true) } catch { setRecording(false) } }
  }

  const send = async e => {
    e.preventDefault()
    if (!text.trim()) return
    setBusy(true); setErr('')
    try {
      if (recording) { recog.current?.stop(); setRecording(false) }
      const participantKey = `pantry.participant.${token}`
      let participant = token ? localStorage.getItem(participantKey) : null
      if (token && !participant) {
        participant = crypto.randomUUID()
        localStorage.setItem(participantKey, participant)
      }
      await api.submitFeedback({
        ...(token ? { request_link: token, participant_id: participant } : {}),
        text: text.trim(),
        lang,
        channel: recording ? 'voice' : 'web',
      })
      setSent(true); setText('')
    } catch (ex) {
      setErr(ex.offline ? 'We could not send that just now. Please try again shortly.' : ex.message)
    } finally { setBusy(false) }
  }

  if (token && linkBad) return (
    <div className="req-wrap">
      <h1>This link is not active</h1>
      <p>Please ask the charity for a new link.</p>
    </div>
  )

  return (
    <div className="req-wrap">
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 18 }}>
        <select style={{ width: 'auto', fontSize: 17 }} value={lang} onChange={e => setLang(e.target.value)}
                aria-label="Language">
          <option value="en">English</option><option value="zh">中文</option>
          <option value="ms">Melayu</option><option value="ta">தமிழ்</option>
        </select>
        {user && (
          <button style={{ width: 'auto', fontSize: 16, padding: '8px 14px' }}
                  onClick={() => { logout(); nav('/login', { replace: true }) }}>Sign out</button>
        )}
      </div>

      <h1>{t.title}</h1>
      <p className="muted" style={{ fontSize: 18 }}>
        {link ? `${link.charity_name} — ${t.hint}` : t.hint}
      </p>

      {sent ? (
        <>
          <div className="banner banner-ok" style={{ fontSize: 19 }}>{t.thanks}</div>
          <button onClick={() => setSent(false)}>{t.again}</button>
        </>
      ) : (
        <form onSubmit={send}>
          <Banner>{err}</Banner>
          <textarea value={text} onChange={e => setText(e.target.value)}
                    placeholder={t.ph} aria-label={t.title} />
          <div style={{ height: 12 }} />
          {!voiceUnsupported && (
            <>
              <button type="button" className={'btn-mic' + (recording ? ' rec' : '')}
                      onClick={toggleMic}>
                {recording ? `● ${t.stop}` : `🎤 ${t.mic}`}
              </button>
              <div style={{ height: 10 }} />
            </>
          )}
          <button className="btn-primary" disabled={busy || !text.trim()}>
            {busy ? '…' : t.send}
          </button>
        </form>
      )}
    </div>
  )
}

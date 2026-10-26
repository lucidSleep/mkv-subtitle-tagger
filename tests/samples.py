"""Test fixtures: the same 30 lines of everyday dialogue in several languages, and subtitle file writers.

The sentences were written for these tests (no film or series subtitles), so they can be published.
The two Portuguese versions carry the variant words identify_subs.py looks for (você / a gente / tá
against tu / estás / rapariga / fixe).
"""

from pathlib import Path
from typing import Dict, List

SAMPLES: Dict[str, List[str]] = {
    "eng": [
        "Where have you been all morning?", "I was waiting for you at the station.",
        "The train was late again, as usual.", "We need to talk about what happened yesterday.",
        "I don't think this is a good idea.", "Can you tell me why she left so early?",
        "Nobody knows where he keeps the keys.", "Let's get out of here before it starts raining.",
        "My brother is coming to visit next weekend.", "Have you seen the news this evening?",
        "They say the bridge will be closed for a month.", "I'm sorry, I didn't mean to wake you up.",
        "Put the box on the table and sit down.", "This coffee is much too sweet for me.",
        "We should have called the police straight away.", "Why would anyone want to steal an old car?",
        "The children are playing in the garden.", "I'll explain everything when we get home.",
        "Do you remember the name of that restaurant?", "It was the best holiday we ever had.",
        "Turn off the lights when you leave the office.", "He promised he would never lie to me again.",
        "Wait here, I'll be back in five minutes.", "Something strange is going on in this town.",
        "Thank you for everything you have done for us.", "Are you sure you locked the front door?",
        "The meeting has been moved to Thursday afternoon.", "She has been working at the hospital for years.",
        "I can't believe you kept this secret from me.", "Good night, and drive carefully.",
    ],
    "fre": [
        "Où étais-tu toute la matinée ?", "Je t'attendais à la gare.",
        "Le train était encore en retard, comme d'habitude.", "Il faut qu'on parle de ce qui s'est passé hier.",
        "Je ne crois pas que ce soit une bonne idée.", "Tu peux me dire pourquoi elle est partie si tôt ?",
        "Personne ne sait où il range les clés.", "Partons d'ici avant qu'il commence à pleuvoir.",
        "Mon frère vient nous rendre visite le week-end prochain.", "Tu as vu les informations ce soir ?",
        "On dit que le pont sera fermé pendant un mois.", "Je suis désolé, je ne voulais pas te réveiller.",
        "Pose la boîte sur la table et assieds-toi.", "Ce café est beaucoup trop sucré pour moi.",
        "On aurait dû appeler la police tout de suite.", "Pourquoi quelqu'un voudrait voler une vieille voiture ?",
        "Les enfants jouent dans le jardin.", "Je t'expliquerai tout quand on sera à la maison.",
        "Tu te souviens du nom de ce restaurant ?", "Ce sont les meilleures vacances qu'on ait jamais eues.",
        "Éteins les lumières quand tu quittes le bureau.", "Il m'a promis qu'il ne me mentirait plus jamais.",
        "Attends ici, je reviens dans cinq minutes.", "Il se passe quelque chose de bizarre dans cette ville.",
        "Merci pour tout ce que vous avez fait pour nous.", "Tu es sûr d'avoir fermé la porte d'entrée à clé ?",
        "La réunion a été déplacée à jeudi après-midi.", "Elle travaille à l'hôpital depuis des années.",
        "Je n'arrive pas à croire que tu m'aies caché ça.", "Bonne nuit, et conduis prudemment.",
    ],
    "ger": [
        "Wo warst du den ganzen Morgen?", "Ich habe am Bahnhof auf dich gewartet.",
        "Der Zug hatte wieder Verspätung, wie immer.", "Wir müssen darüber reden, was gestern passiert ist.",
        "Ich glaube nicht, dass das eine gute Idee ist.", "Kannst du mir sagen, warum sie so früh gegangen ist?",
        "Niemand weiß, wo er die Schlüssel aufbewahrt.", "Lass uns hier verschwinden, bevor es anfängt zu regnen.",
        "Mein Bruder kommt nächstes Wochenende zu Besuch.", "Hast du heute Abend die Nachrichten gesehen?",
        "Es heißt, die Brücke wird einen Monat lang gesperrt.", "Entschuldige, ich wollte dich nicht wecken.",
        "Stell die Kiste auf den Tisch und setz dich.", "Dieser Kaffee ist mir viel zu süß.",
        "Wir hätten sofort die Polizei rufen sollen.", "Warum sollte jemand ein altes Auto stehlen wollen?",
        "Die Kinder spielen im Garten.", "Ich erkläre dir alles, wenn wir zu Hause sind.",
        "Erinnerst du dich an den Namen dieses Restaurants?", "Das war der schönste Urlaub, den wir je hatten.",
        "Mach das Licht aus, wenn du das Büro verlässt.", "Er hat mir versprochen, mich nie wieder anzulügen.",
        "Warte hier, ich bin in fünf Minuten zurück.", "In dieser Stadt geht etwas Seltsames vor sich.",
        "Danke für alles, was ihr für uns getan habt.", "Bist du sicher, dass du die Haustür abgeschlossen hast?",
        "Das Treffen wurde auf Donnerstagnachmittag verschoben.", "Sie arbeitet seit Jahren im Krankenhaus.",
        "Ich kann nicht glauben, dass du das vor mir verheimlicht hast.", "Gute Nacht, und fahr vorsichtig.",
    ],
    "ita": [
        "Dove sei stato tutta la mattina?", "Ti stavo aspettando alla stazione.",
        "Il treno era di nuovo in ritardo, come al solito.", "Dobbiamo parlare di quello che è successo ieri.",
        "Non credo che sia una buona idea.", "Puoi dirmi perché se n'è andata così presto?",
        "Nessuno sa dove tiene le chiavi.", "Andiamocene prima che cominci a piovere.",
        "Mio fratello viene a trovarci il prossimo fine settimana.", "Hai visto il telegiornale stasera?",
        "Dicono che il ponte resterà chiuso per un mese.", "Scusa, non volevo svegliarti.",
        "Metti la scatola sul tavolo e siediti.", "Questo caffè è troppo dolce per me.",
        "Avremmo dovuto chiamare subito la polizia.", "Perché qualcuno dovrebbe rubare una vecchia macchina?",
        "I bambini stanno giocando in giardino.", "Ti spiegherò tutto quando saremo a casa.",
        "Ti ricordi il nome di quel ristorante?", "È stata la vacanza più bella che abbiamo mai fatto.",
        "Spegni le luci quando esci dall'ufficio.", "Mi ha promesso che non mi avrebbe mai più mentito.",
        "Aspetta qui, torno tra cinque minuti.", "Sta succedendo qualcosa di strano in questa città.",
        "Grazie per tutto quello che avete fatto per noi.", "Sei sicuro di aver chiuso a chiave la porta d'ingresso?",
        "La riunione è stata spostata a giovedì pomeriggio.", "Lavora all'ospedale da anni.",
        "Non posso credere che tu mi abbia tenuto nascosto questo segreto.", "Buonanotte, e guida con prudenza.",
    ],
    "spa": [
        "¿Dónde has estado toda la mañana?", "Te estaba esperando en la estación.",
        "El tren volvió a llegar tarde, como siempre.", "Tenemos que hablar de lo que pasó ayer.",
        "No creo que sea una buena idea.", "¿Puedes decirme por qué se fue tan temprano?",
        "Nadie sabe dónde guarda las llaves.", "Vámonos de aquí antes de que empiece a llover.",
        "Mi hermano viene a visitarnos el próximo fin de semana.", "¿Has visto las noticias esta noche?",
        "Dicen que el puente estará cerrado durante un mes.", "Lo siento, no quería despertarte.",
        "Pon la caja en la mesa y siéntate.", "Este café está demasiado dulce para mí.",
        "Deberíamos haber llamado a la policía enseguida.", "¿Por qué querría alguien robar un coche viejo?",
        "Los niños están jugando en el jardín.", "Te lo explicaré todo cuando lleguemos a casa.",
        "¿Te acuerdas del nombre de ese restaurante?", "Fueron las mejores vacaciones que hemos tenido.",
        "Apaga las luces cuando salgas de la oficina.", "Me prometió que nunca volvería a mentirme.",
        "Espera aquí, vuelvo en cinco minutos.", "Algo extraño está pasando en este pueblo.",
        "Gracias por todo lo que habéis hecho por nosotros.", "¿Seguro que cerraste la puerta de entrada con llave?",
        "La reunión se ha cambiado al jueves por la tarde.", "Ella lleva años trabajando en el hospital.",
        "No puedo creer que me hayas ocultado este secreto.", "Buenas noches, y conduce con cuidado.",
    ],
    "por-BR": [
        "Onde você esteve a manhã inteira?", "Eu estava esperando você na estação.",
        "O trem atrasou de novo, como sempre.", "A gente precisa conversar sobre o que aconteceu ontem.",
        "Acho que isso não é uma boa ideia, cara.", "Você pode me dizer por que ela saiu tão cedo?",
        "Ninguém sabe onde ele guarda as chaves.", "Vamos sair daqui antes que comece a chover.",
        "Meu irmão vem visitar a gente no próximo fim de semana.", "Você viu o jornal hoje à noite?",
        "Dizem que a ponte vai ficar fechada por um mês.", "Desculpa, eu não queria acordar você.",
        "Coloca a caixa na mesa e senta aí.", "Esse café tá doce demais pra mim.",
        "A gente devia ter chamado a polícia na hora.", "Por que alguém ia querer roubar um carro velho?",
        "As crianças estão brincando no jardim.", "Eu explico tudo quando a gente chegar em casa.",
        "Você lembra o nome daquele restaurante?", "Foram as melhores férias que a gente já teve.",
        "Apaga as luzes quando você sair do escritório.", "Ele prometeu que nunca mais ia mentir pra mim.",
        "Espera aqui, eu volto em cinco minutos.", "Tem alguma coisa estranha acontecendo nessa cidade.",
        "Valeu por tudo que vocês fizeram pela gente.", "Você tem certeza que trancou a porta da frente?",
        "A reunião foi transferida pra quinta à tarde.", "Ela trabalha no hospital há anos.",
        "Não acredito que você escondeu isso de mim.", "Boa noite, e dirige com cuidado, tá?",
    ],
    "por-PT": [
        "Onde é que tu estiveste a manhã toda?", "Estava à tua espera na estação.",
        "O comboio voltou a atrasar-se, como de costume.", "Temos de falar sobre o que aconteceu ontem.",
        "Não me parece que seja boa ideia.", "Podes dizer-me porque é que ela saiu tão cedo?",
        "Ninguém sabe onde ele guarda as chaves.", "Vamos embora antes que comece a chover.",
        "O meu irmão vem visitar-nos no próximo fim de semana.", "Viste o telejornal esta noite?",
        "Dizem que a ponte vai estar fechada durante um mês.", "Desculpa, não te queria acordar.",
        "Põe a caixa em cima da mesa e senta-te.", "Este café está demasiado doce para mim.",
        "Devíamos ter chamado a polícia logo.", "Porque é que alguém havia de roubar um carro velho?",
        "Os miúdos estão a brincar no jardim.", "Explico-te tudo quando chegarmos a casa.",
        "Lembras-te do nome daquele restaurante?", "Foram as melhores férias que alguma vez tivemos.",
        "Apaga as luzes quando saíres do escritório.", "Ele prometeu que nunca mais me mentia.",
        "Espera aqui, volto daqui a cinco minutos.", "Está a acontecer uma coisa estranha nesta cidade.",
        "Obrigado por tudo o que fizeram por nós.", "Tens a certeza de que fechaste a porta da frente à chave?",
        "A reunião passou para quinta-feira à tarde.", "Ela trabalha no hospital há anos, é uma rapariga fixe.",
        "Não acredito que me escondeste isto.", "Boa noite, e conduz com cuidado, estás a ouvir?",
    ],
    "chi-Hans": [
        "你今天早上去哪儿了？", "我在车站等你。", "火车又晚点了，跟平时一样。", "我们得谈谈昨天发生的事。",
        "我觉得这不是个好主意。", "你能告诉我她为什么走得这么早吗？", "没有人知道他把钥匙放在哪里。",
        "我们在下雨之前离开这里吧。", "我哥哥下个周末来看我们。", "你今晚看新闻了吗？", "听说那座桥要关闭一个月。",
        "对不起，我不是故意吵醒你的。", "把箱子放在桌子上，坐下吧。", "这杯咖啡对我来说太甜了。",
        "我们应该马上报警的。", "为什么有人会想偷一辆旧车？", "孩子们在花园里玩。", "等我们到家，我会把一切都告诉你。",
        "你还记得那家饭店的名字吗？", "那是我们过得最开心的假期。", "离开办公室的时候请把灯关掉。",
        "他答应过我再也不会对我说谎。", "在这里等着，我五分钟后回来。", "这个城市里正在发生奇怪的事情。",
        "谢谢你们为我们做的一切。", "你确定锁好前门了吗？", "会议改到星期四下午了。", "她在医院工作好多年了。",
        "真不敢相信你一直瞒着我。", "晚安，开车小心。",
    ],
    "chi-Hant": [
        "你今天早上去哪兒了？", "我在車站等你。", "火車又晚點了，跟平時一樣。", "我們得談談昨天發生的事。",
        "我覺得這不是個好主意。", "你能告訴我她為什麼走得這麼早嗎？", "沒有人知道他把鑰匙放在哪裡。",
        "我們在下雨之前離開這裡吧。", "我哥哥下個週末來看我們。", "你今晚看新聞了嗎？", "聽說那座橋要關閉一個月。",
        "對不起，我不是故意吵醒你的。", "把箱子放在桌子上，坐下吧。", "這杯咖啡對我來說太甜了。",
        "我們應該馬上報警的。", "為什麼有人會想偷一輛舊車？", "孩子們在花園裡玩。", "等我們到家，我會把一切都告訴你。",
        "你還記得那家飯店的名字嗎？", "那是我們過得最開心的假期。", "離開辦公室的時候請把燈關掉。",
        "他答應過我再也不會對我說謊。", "在這裡等著，我五分鐘後回來。", "這個城市裡正在發生奇怪的事情。",
        "謝謝你們為我們做的一切。", "你確定鎖好前門了嗎？", "會議改到星期四下午了。", "她在醫院工作好多年了。",
        "真不敢相信你一直瞞著我。", "晚安，開車小心。",
    ],
}

# English for the deaf and hard of hearing: the same dialogue plus sound cues and speaker labels.
SDH_CUES: List[str] = ["[door slams]", "[phone ringing]", "(sighs)", "[footsteps approaching]", "[thunder rumbling]",
                       "[engine starts]", "(laughs)", "[dog barking]", "[music playing]", "[knocking on door]"]


def with_sound_cues(lines: List[str]) -> List[str]:
    """A sound cue after every third line: 10 of the 40 lines, like a real SDH track."""
    result: List[str] = []
    for index, line in enumerate(lines):
        result.append(line)
        if index % 3 == 0:
            result.append(SDH_CUES[index // 3])
    return result


SAMPLES["eng-SDH"] = with_sound_cues(SAMPLES["eng"])

# A "forced" track: only the few lines of a scene in another language.
SAMPLES["eng-forced"] = ["Stop right there!", "Who sent you here?", "Put the gun down."]


def timestamp(seconds: int, separator: str = ",") -> str:
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}{separator}000"


def write_srt(path: Path, lines: List[str]) -> Path:
    blocks: List[str] = [f"{number}\n{timestamp(number * 3)} --> {timestamp(number * 3 + 2)}\n<i>{line}</i>\n"
                         for number, line in enumerate(lines, start=1)]
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def write_vtt(path: Path, lines: List[str]) -> Path:
    blocks: List[str] = ["WEBVTT\n", "NOTE written by the tests\n"]
    blocks += [f"{timestamp(number * 3, '.')} --> {timestamp(number * 3 + 2, '.')}\n{line}\n"
               for number, line in enumerate(lines, start=1)]
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def write_ass(path: Path, lines: List[str]) -> Path:
    header: str = ("[Script Info]\nScriptType: v4.00+\n\n[V4+ Styles]\n"
                   "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
                   "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                   "Alignment, MarginL, MarginR, MarginV, Encoding\n"
                   "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,"
                   "2,10,10,10,1\n\n[Events]\n"
                   "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    events: List[str] = []
    for number, line in enumerate(lines, start=1):
        start, end = number * 3, number * 3 + 2
        # Split long lines with \N and put an override tag in, as real .ass files do.
        text: str = line.replace(", ", ",\\N", 1)
        events.append(f"Dialogue: 0,0:{start // 60:02d}:{start % 60:02d}.00,0:{end // 60:02d}:{end % 60:02d}.00,"
                      f"Default,,0,0,0,,{{\\i1}}{text}")
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return path

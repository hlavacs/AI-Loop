Create an introduction video for youtube.
Length 10-12 minutes
White background, logo of the university of Vienna on every slide in the right upper corner (large enough to read easily, not too large) : https://www.univie.ac.at/en/about-us/organisation-and-structure/corporate-communications/downloads
Keep the slides simple, and graphical. Do not put too much visual styles in a slide.
You pronounce my family name starting with an "L", the ending is like the one from "couch" or the starting from "cheese". Just say my name, do not stress the point that this is how it is pronounced.
Introduction, something about me, university affiliation, university Web site, university email, GitHub repo. Mention my company Robimo.at at the end of the presentation as service provider specialized in AI tooling. Do not speak GmBH, you have it wrong.
Put my name and university affiliation also onto the title slide, use my web page : "https://entertain.univie.ac.at/~hlavacs/" , not the university page. Do not spell out the URLs.
In the video discuss what it is for, basic idea, mental model, how it works
Introduce GUI with screenshots, many screenshots. Explain what you can see on a screenshot.
Make sure that each screenshot fits into the slide area it is supposed to go.
In diagrams arrows should never overlap with other diagram objects, but be hidden behind objects of they would otherwise overlap. 
Make sure the spoken language follows normal speech patterns, espcially with respect to ending sentences or ending sentence parts. At the end of a sentence the intonation must signal this end somehow. So for all spoken text make sure that proper interpunctation signals to ElevenLabs the ending of sentences or sentence parts.
Introduce simple but complete examples. Start with the idea of a new project, the show on screen what to do next. 
Do this to show the flow of input and interactions with the user and what the user sees. This interaction demonstration should catch all steps, inut and output, like a pseudo video capture.
Use some form of highlighting to point to specific parts of the GUI that are important at this moment, like a red rectangle, or an arrow.
Use ElevenLabs for the voicing.
Use the configured ElevenLabs MCP connector through OAuth. Do not call the ElevenLabs REST API directly and do not search for ELEVENLABS_API_KEY. Generate speech with “Helmut Lecture 2”, synchronize it with the visuals, produce the final MP4 files, and validate them with ffprobe.

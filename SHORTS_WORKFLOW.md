# @Bizstring Shorts: build rules

Claude builds every Short start to finish and hands over one MP4 that is ready to upload.

## Fixed settings
- Character: reference image `Original cut-paper still | cart.png` (ElevenLabs asset `jmRhz6oMhhyHiHj4STPA`).
  Man with dark wavy hair and stubble, mustard-yellow jacket, white t-shirt, indigo jeans, layered paper-craft style, cream/teal/red palette.
- Voice: "Mikes narrator voice clone (1st run)", voice ID `KPBiWzMZzowmxmABiR0Q`, model `eleven_multilingual_v2`, 1 take.
- Images: `gemini-3-pro-image`, aspect ratio **9:16 set on the node before running**, 1 variation. About 1,827 credits each.
- Motion: `kling-2.5-turbo`, 5 s, aspect **9:16 set on the node before running**. About 2,121 credits each.
- Audio in the final MP4: AAC 256k, original level, no loudness filter.

## Saving credits
1. Check the scene library first (`short1/`, `short2/`, and the ElevenLabs flows). Reuse before generating.
2. List reused vs new assets and the credit total before spending. Default cap: 20,000 credits per Short.
3. AI motion only on the 2 or 3 scenes where something has to happen. Everything else gets a free push-in in the edit.
4. Never generate a second take to retry. Fix the prompt and run once.

## Video format
- 30 to 60 seconds. Hook in the first 2 seconds, about the viewer, not an accusation.
- Picture changes every 3 to 5 seconds. Captions burned in. Section badge at the top for list videos.
- End card: @Bizstring, comment question, like and share.
- Pinned comment carries the test link: dark-side-test.netlify.app

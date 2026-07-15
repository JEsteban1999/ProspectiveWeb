import { Composition } from "remotion";
import { Pipeline, PIPELINE_DURATION, FPS } from "./Pipeline";

export const RemotionRoot = () => {
  return (
    <Composition
      id="Pipeline"
      component={Pipeline}
      durationInFrames={PIPELINE_DURATION}
      fps={FPS}
      width={1280}
      height={720}
    />
  );
};
